"""A labeled video dataset: a reference to one exact video file plus the frames a human marked.

See specs/features/labeled-video-dataset.md. Only the video's identity and the marked frames are
stored (data/datasets/<video-id>.yaml); the frames themselves are decoded from the video on demand.
A frame is identified by its 0-based index in sequential decoding, and its timestamp is that
frame's own presentation time, exactly as `extract_memes.frame_extractor.sample_frames` reports it.
"""

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

SCHEMA = 1
DATASETS_DIR = Path("data/datasets")
DOWNLOADS_DIR = Path(".runtime/downloads")
EXCLUSION_WINDOW_SECONDS = 1.0
_TS_TOLERANCE = 0.0005  # `meme_ts` is stored with 3 decimals


class DatasetError(RuntimeError):
    """A dataset file or its video is unusable."""


@dataclass
class VideoInfo:
    """Which video file was labeled: enough to download the same encode again and to check it."""

    url: str
    id: str
    format_id: str
    vcodec: str
    ext: str
    width: int
    height: int
    fps: float
    frame_count: int  # as the container reports it (CAP_PROP_FRAME_COUNT), not a decoded count


@dataclass(frozen=True)
class Meme:
    """One marked meme: any one frame while it is on screen (`meme_frame`, the anchor).

    The precise labeling can also record where it starts and ends; an edge left unset means the
    anchor. The anchor always lies between the edges.
    """

    meme_ts: float
    meme_frame: int
    start_ts: float | None = None
    start_frame: int | None = None
    end_ts: float | None = None
    end_frame: int | None = None

    @property
    def first(self) -> int:
        return self.meme_frame if self.start_frame is None else self.start_frame

    @property
    def last(self) -> int:
        return self.meme_frame if self.end_frame is None else self.end_frame

    def contains(self, frame: int) -> bool:
        return self.first <= frame <= self.last


@dataclass(frozen=True)
class NotMeme:
    """A frame the human explicitly marked as not a meme (a hard negative)."""

    not_meme_ts: float
    not_meme_frame: int


@dataclass
class Dataset:
    video: VideoInfo
    memes: list[Meme] = field(default_factory=list)
    not_memes: list[NotMeme] = field(default_factory=list)
    mode: str = "standard"

    def meme_at(self, frame: int) -> Meme | None:
        """The meme whose start..end covers `frame`."""
        return next((m for m in self.memes if m.contains(frame)), None)

    def add(self, frame: int, ts: float) -> None:
        """Mark `frame` as a meme (replacing any label it had), keeping the memes sorted.

        A frame inside a meme that is already marked changes nothing.
        """
        self.remove_not_meme(frame)
        if self.meme_at(frame):
            return
        self.memes = sorted(self.memes + [Meme(round(ts, 3), frame)], key=lambda m: m.meme_frame)

    def remove(self, frame: int) -> None:
        """Unmark the meme `frame` belongs to (the whole meme, if it has a start and end)."""
        self.memes = [m for m in self.memes if not m.contains(frame)]

    def nearest_meme(self, frame: int, ts_of: Callable[[int], float], window: float) -> Meme | None:
        """The meme covering `frame`, else the one whose start..end is closest within `window` seconds."""
        found = self.meme_at(frame)
        if found:
            return found
        here = ts_of(frame)
        near = [(min(abs(ts_of(m.first) - here), abs(ts_of(m.last) - here)), m) for m in self.memes]
        near = [(d, m) for d, m in near if d <= window]
        return min(near, key=lambda pair: pair[0])[1] if near else None

    def set_edge(self, frame: int, edge: str, ts_of: Callable[[int], float], window: float) -> None:
        """Make `frame` the start or the end of a meme: the one `nearest_meme` finds, else a new one.

        Raises `ValueError` if that would put the start after the end or overlap another meme.
        """
        if edge not in ("start", "end"):
            raise ValueError("edge must be 'start' or 'end'")
        target = self.nearest_meme(frame, ts_of, window)
        if target is None:
            first, last, anchor = frame, frame, frame
            start = end = None
        else:
            start, end, anchor = target.start_frame, target.end_frame, target.meme_frame
            first, last = target.first, target.last
        if edge == "start":
            if end is not None and frame > end:
                raise ValueError("the start can't be after the end")
            start, first = frame, frame
            if last < frame:
                last = anchor = frame
        else:
            if start is not None and frame < start:
                raise ValueError("the end can't be before the start")
            end, last = frame, frame
            if first > frame:
                first = anchor = frame
        anchor = min(max(anchor, first), last)
        others = [m for m in self.memes if m is not target]
        if any(m.first <= last and first <= m.last for m in others):
            raise ValueError("a meme can't overlap another meme")
        made = Meme(
            round(ts_of(anchor), 3), anchor,
            None if start is None else round(ts_of(start), 3), start,
            None if end is None else round(ts_of(end), 3), end,
        )
        self.memes = sorted(others + [made], key=lambda m: m.meme_frame)
        self.remove_not_meme_in(first, last)

    def set_range(self, first: int, last: int, ts_of: Callable[[int], float]) -> None:
        """Make `first`..`last` one meme, replacing every meme that overlaps it.

        The meme keeps the frame of the first replaced meme that lay inside the window as its own
        frame (else `first`), and any not-meme inside the window is dropped.
        """
        if first > last:
            raise ValueError("the start can't be after the end")
        overlapped = [m for m in self.memes if m.first <= last and first <= m.last]
        inside = [m.meme_frame for m in overlapped if first <= m.meme_frame <= last]
        anchor = inside[0] if inside else first
        made = Meme(round(ts_of(anchor), 3), anchor, round(ts_of(first), 3), first, round(ts_of(last), 3), last)
        self.memes = sorted([m for m in self.memes if m not in overlapped] + [made], key=lambda m: m.meme_frame)
        self.remove_not_meme_in(first, last)

    def add_many(self, frames: list[int], ts_of: Callable[[int], float]) -> None:
        """Mark `frames` as memes: each run of consecutive frames becomes one start..end meme and a
        frame on its own a single-frame meme. A region absorbs the memes it overlaps."""
        runs: list[list[int]] = []
        for frame in sorted(set(frames)):
            if runs and frame == runs[-1][-1] + 1:
                runs[-1].append(frame)
            else:
                runs.append([frame])
        for run in runs:
            if len(run) > 1:
                self.set_range(run[0], run[-1], ts_of)
        for run in runs:
            if len(run) == 1:
                self.remove_not_meme(run[0])
                if not self.meme_at(run[0]):
                    self.add(run[0], ts_of(run[0]))

    def remove_not_meme_in(self, first: int, last: int) -> None:
        self.not_memes = [n for n in self.not_memes if not first <= n.not_meme_frame <= last]

    def add_not_meme(self, frame: int, ts: float) -> None:
        """Mark `frame` as not a meme (replacing any label it had), keeping the list sorted."""
        inside = self.meme_at(frame)
        if inside and (inside.start_frame is not None or inside.end_frame is not None):
            raise ValueError("that frame is inside a meme's start..end; unmark the meme first")
        self.remove(frame)
        self.not_memes = sorted(
            [n for n in self.not_memes if n.not_meme_frame != frame] + [NotMeme(round(ts, 3), frame)],
            key=lambda n: n.not_meme_frame,
        )

    def remove_not_meme(self, frame: int) -> None:
        self.not_memes = [n for n in self.not_memes if n.not_meme_frame != frame]


def dataset_path(video_id: str, datasets_dir: Path = DATASETS_DIR) -> Path:
    return datasets_dir / f"{video_id}.yaml"


def video_id_from(source: str) -> str:
    """The YouTube video id of a URL, or `source` itself when it already is a bare id."""
    if re.fullmatch(r"[\w-]{11}", source):
        return source
    match = re.search(r"(?:[?&]v=|youtu\.be/|/shorts/|/embed/)([\w-]{11})", source)
    if not match:
        raise DatasetError(f"Could not find a YouTube video id in {source!r}")
    return match.group(1)


def canonical_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def list_datasets(datasets_dir: Path = DATASETS_DIR) -> list[dict]:
    """`{id, memes, not_memes}` for every readable dataset file, so a page can offer them."""
    found = []
    for path in sorted(datasets_dir.glob("*.yaml")):
        try:
            dataset = load(path)
        except (DatasetError, OSError, ValueError):
            continue
        found.append({"id": dataset.video.id, "memes": len(dataset.memes), "not_memes": len(dataset.not_memes)})
    return found


def _meme_line(m: Meme) -> str:
    parts = [f"meme_ts: {m.meme_ts:.3f}", f"meme_frame: {m.meme_frame}"]
    if m.start_frame is not None:
        parts += [f"meme_start_ts: {m.start_ts:.3f}", f"meme_start_frame: {m.start_frame}"]
    if m.end_frame is not None:
        parts += [f"meme_end_ts: {m.end_ts:.3f}", f"meme_end_frame: {m.end_frame}"]
    return "{" + ", ".join(parts) + "}"


def _read_meme(entry: dict) -> Meme:
    def edge(name: str) -> tuple[float | None, int | None]:
        frame = entry.get(f"meme_{name}_frame")
        return (None, None) if frame is None else (float(entry[f"meme_{name}_ts"]), int(frame))

    (start_ts, start_frame), (end_ts, end_frame) = edge("start"), edge("end")
    return Meme(float(entry["meme_ts"]), int(entry["meme_frame"]), start_ts, start_frame, end_ts, end_frame)


def save(dataset: Dataset, path: Path) -> None:
    """Write `dataset` to `path` as YAML, creating the folder, with one meme per line."""
    import yaml

    video = dataset.video
    header = {
        "schema": SCHEMA,
        "mode": dataset.mode,
        "video": {
            "url": video.url,
            "id": video.id,
            "format_id": str(video.format_id),
            "vcodec": video.vcodec,
            "ext": video.ext,
            "width": video.width,
            "height": video.height,
            "fps": video.fps,
            "frame_count": video.frame_count,
        },
    }
    text = yaml.safe_dump(header, sort_keys=False, default_flow_style=False)
    if dataset.memes:
        text += "memes:\n" + "".join(f"  - {_meme_line(m)}\n" for m in dataset.memes)
    else:
        text += "memes: []\n"
    if dataset.not_memes:
        text += "not_memes:\n" + "".join(
            f"  - {{not_meme_ts: {n.not_meme_ts:.3f}, not_meme_frame: {n.not_meme_frame}}}\n"
            for n in dataset.not_memes
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(text, encoding="utf-8")
    temp.replace(path)  # a crash mid-write never leaves a half-written dataset


def load(path: Path) -> Dataset:
    """Read a dataset file, raising `DatasetError` for anything the loader doesn't support."""
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if data.get("schema") != SCHEMA:
        raise DatasetError(f"{path}: unsupported schema {data.get('schema')!r} (expected {SCHEMA})")
    mode = data.get("mode")
    if mode == "precise":
        raise DatasetError(f"{path}: precise mode is not supported yet")
    if mode != "standard":
        raise DatasetError(f"{path}: unknown mode {mode!r}")
    try:
        video = VideoInfo(**{**data["video"], "format_id": str(data["video"]["format_id"])})
        memes = [_read_meme(m) for m in data.get("memes") or []]
        not_memes = [
            NotMeme(float(n["not_meme_ts"]), int(n["not_meme_frame"])) for n in data.get("not_memes") or []
        ]
    except (KeyError, TypeError) as exc:
        raise DatasetError(f"{path}: malformed dataset ({exc!r})") from exc
    frames = [m.meme_frame for m in memes]
    if frames != sorted(set(frames)):
        raise DatasetError(f"{path}: memes must be sorted by frame with no duplicates")
    if any(m.first > m.meme_frame or m.meme_frame > m.last for m in memes) or any(
        a.last >= b.first for a, b in zip(memes, memes[1:])
    ):
        raise DatasetError(f"{path}: a meme's frame must lie between its start and end, and memes can't overlap")
    not_frames = [n.not_meme_frame for n in not_memes]
    if not_frames != sorted(set(not_frames)):
        raise DatasetError(f"{path}: not_memes must be sorted by frame with no duplicates")
    if any(m.contains(f) for m in memes for f in not_frames):
        raise DatasetError(f"{path}: a frame can't be both a meme and a not-meme")
    return Dataset(video=video, memes=memes, not_memes=not_memes, mode=mode)


# --- Video file -----------------------------------------------------------------------------------


def probe(video_path: Path) -> tuple[int, int, float, int]:
    """`(width, height, fps, frame_count)` of a video file, as the container reports them."""
    cap = cv2.VideoCapture(str(video_path))
    try:
        if not cap.isOpened():
            raise DatasetError(f"Could not open video file: {video_path}")
        return (
            int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            round(cap.get(cv2.CAP_PROP_FPS), 3),
            int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        )
    finally:
        cap.release()


def validate_video(video: VideoInfo, video_path: Path) -> None:
    """Raise `DatasetError` naming the first property of the file that differs from the dataset."""
    width, height, fps, frame_count = probe(video_path)
    for name, actual in (("width", width), ("height", height), ("fps", fps), ("frame_count", frame_count)):
        recorded = getattr(video, name)
        if (abs(actual - recorded) > 0.001) if name == "fps" else (actual != recorded):
            raise DatasetError(
                f"{video_path} is not the labeled video: {name} is {actual}, the dataset says {recorded}"
            )


def downloaded_path(video_id: str, format_id: str, ext: str, downloads_dir: Path = DOWNLOADS_DIR) -> Path:
    return downloads_dir / f"{video_id}_{format_id}.{ext}"


def download_format(
    url: str,
    format_selector: str,
    downloads_dir: Path = DOWNLOADS_DIR,
    proxy: str | None = None,
    progress: Callable[[str, float | None], None] | None = None,
) -> tuple[Path, VideoInfo]:
    """Download one yt-dlp format of `url` to `downloads_dir/<id>_<format_id>.<ext>`.

    `format_selector` is a yt-dlp format string, which for a dataset reload is the recorded
    `format_id`. Returns the file and what it is (frame count read from the downloaded file).
    `progress(message, fraction)` is called as the download advances.
    """
    import static_ffmpeg
    import yt_dlp

    downloads_dir.mkdir(parents=True, exist_ok=True)
    static_ffmpeg.add_paths()
    options = {
        "format": format_selector,
        "outtmpl": str(downloads_dir / "%(id)s_%(format_id)s.%(ext)s"),
        "js_runtimes": {"node": {}},
        "quiet": True,
    }
    if proxy:
        options["proxy"] = proxy
    if progress:
        def hook(status: dict) -> None:
            if status.get("status") != "downloading":
                return
            if status.get("fragment_count"):
                fraction = (status.get("fragment_index") or 0) / status["fragment_count"]
            else:
                total = status.get("total_bytes") or status.get("total_bytes_estimate")
                fraction = status.get("downloaded_bytes", 0) / total if total else None
            progress("Downloading video", fraction)

        options["progress_hooks"] = [hook]
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
            path = Path(ydl.prepare_filename(info))
    except Exception as exc:
        raise DatasetError(f"Failed to download {url!r} as format {format_selector!r}: {exc}") from exc
    width, height, fps, frame_count = probe(path)
    return path, VideoInfo(
        url=url,
        id=info["id"],
        format_id=str(info["format_id"]),
        vcodec=info.get("vcodec") or "unknown",
        ext=info["ext"],
        width=width,
        height=height,
        fps=fps,
        frame_count=frame_count,
    )


def preferred_format(formats: list[dict]) -> str | None:
    """The format id to preselect: at least 25 fps first, then the smallest resolution, then not AV1.

    Each rule only breaks ties of the one before, so a 25 fps AV1 format beats a 24 fps H.264 one
    of the same size. Remaining ties keep the order given (smallest known file first).
    """
    if not formats:
        return None
    best = min(
        formats,
        key=lambda f: (
            0 if (f.get("fps") or 0) >= 25 else 1,
            (f.get("height") or 0) * (f.get("width") or 0),
            1 if f.get("av1") else 0,
        ),
    )
    return best["format_id"]


def fetch_video_info(url: str, proxy: str | None = None) -> dict:
    """What a YouTube video is and which video formats it offers; nothing is downloaded."""
    import yt_dlp

    options = {"quiet": True, "noprogress": True, "skip_download": True, "js_runtimes": {"node": {}}}
    if proxy:
        options["proxy"] = proxy
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        raise DatasetError(f"Could not look up {url!r}: {exc}") from exc
    formats = []
    for f in info.get("formats") or []:
        if (f.get("vcodec") or "none") == "none" or not f.get("width"):
            continue  # audio only, or a storyboard
        formats.append({
            "format_id": str(f["format_id"]),
            "ext": f.get("ext"),
            "vcodec": f.get("vcodec"),
            "width": f.get("width"),
            "height": f.get("height"),
            "fps": f.get("fps"),
            "size": f.get("filesize") or f.get("filesize_approx"),
            "av1": str(f.get("vcodec") or "").startswith("av01"),
        })
    formats.sort(key=lambda f: (f["height"] or 0, f["size"] or 0))
    return {
        "id": info["id"],
        "title": info.get("title"),
        "thumbnail": info.get("thumbnail"),
        "uploader": info.get("uploader"),
        "duration": info.get("duration"),
        "upload_date": info.get("upload_date"),
        "view_count": info.get("view_count"),
        "formats": formats,
        "preselected": preferred_format(formats),
    }


def ensure_video(
    dataset: Dataset,
    downloads_dir: Path = DOWNLOADS_DIR,
    proxy: str | None = None,
    progress: Callable[[str, float | None], None] | None = None,
) -> Path:
    """The local file of the dataset's exact `format_id`, downloaded if absent, and validated."""
    video = dataset.video
    path = downloaded_path(video.id, video.format_id, video.ext, downloads_dir)
    if not path.is_file():
        path, _ = download_format(video.url, video.format_id, downloads_dir, proxy, progress)
    validate_video(video, path)
    return path


# --- Frames ---------------------------------------------------------------------------------------


def iter_frames(
    video_path: Path, wanted: Callable[[int], bool] = lambda index: True
) -> Iterator[tuple[int, float, np.ndarray]]:
    """Yield `(index, timestamp_seconds, frame)` for each wanted frame, decoding sequentially.

    Unwanted frames are only grabbed, not converted. The timestamp is the frame's own presentation
    time (`CAP_PROP_POS_MSEC`), the same as `sample_frames`. Stops at the first failed read.
    """
    cap = cv2.VideoCapture(str(video_path))
    try:
        if not cap.isOpened():
            raise DatasetError(f"Could not open video file: {video_path}")
        index = 0
        while cap.grab():
            if wanted(index):
                timestamp = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000
                ok, frame = cap.retrieve()
                if ok:
                    yield index, timestamp, frame
            index += 1
    finally:
        cap.release()


def scan_step(video_path: Path, fps: float) -> int:
    """Frames between scan samples at `fps`, by the rule `sample_frames` uses."""
    cap = cv2.VideoCapture(str(video_path))
    try:
        native_fps = cap.get(cv2.CAP_PROP_FPS) or fps
    finally:
        cap.release()
    return max(1, round(native_fps / fps))


def _labeled_frames(
    expected: dict[int, float], video_path: Path
) -> Iterator[tuple[int, float, np.ndarray]]:
    for index, timestamp, frame in iter_frames(video_path, expected.__contains__):
        if abs(timestamp - expected[index]) > _TS_TOLERANCE:
            raise DatasetError(
                f"Frame {index} of {video_path} is at {timestamp:.3f}s, the dataset says "
                f"{expected[index]:.3f}s: not the labeled video"
            )
        yield index, timestamp, frame


def positive_frames(dataset: Dataset, video_path: Path) -> Iterator[tuple[int, float, np.ndarray]]:
    """The marked frames, found by sequential decoding; raises if a frame's timestamp disagrees."""
    return _labeled_frames({m.meme_frame: m.meme_ts for m in dataset.memes}, video_path)


def not_meme_frames(dataset: Dataset, video_path: Path) -> Iterator[tuple[int, float, np.ndarray]]:
    """The frames explicitly marked as not a meme, checked like `positive_frames`."""
    return _labeled_frames({n.not_meme_frame: n.not_meme_ts for n in dataset.not_memes}, video_path)


def negative_frames(
    dataset: Dataset,
    video_path: Path,
    fps: float = 3.0,
    exclusion_window: float = EXCLUSION_WINDOW_SECONDS,
) -> Iterator[tuple[int, float, np.ndarray]]:
    """Scan-rate frames more than `exclusion_window` seconds from every mark.

    A meme lasts several frames and standard mode marks one, so the frames around a mark are
    neither positive nor safely negative and are left out; a meme with a start and end is excluded
    from its start to its end, plus the window on both sides.
    """
    step = scan_step(video_path, fps)
    spans = np.array([(m.start_ts if m.start_ts is not None else m.meme_ts,
                       m.end_ts if m.end_ts is not None else m.meme_ts) for m in dataset.memes])
    for index, timestamp, frame in iter_frames(video_path, lambda i: i % step == 0):
        if len(spans) and ((spans[:, 0] - exclusion_window <= timestamp) & (timestamp <= spans[:, 1] + exclusion_window)).any():
            continue
        yield index, timestamp, frame
