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
    """One marked meme (standard mode): any one frame while the meme is on screen."""

    meme_ts: float
    meme_frame: int


@dataclass
class Dataset:
    video: VideoInfo
    memes: list[Meme] = field(default_factory=list)
    mode: str = "standard"

    def add(self, frame: int, ts: float) -> None:
        """Mark `frame` (replacing any mark of the same frame), keeping the memes sorted."""
        self.memes = sorted([m for m in self.memes if m.meme_frame != frame] + [Meme(round(ts, 3), frame)],
                            key=lambda m: m.meme_frame)

    def remove(self, frame: int) -> None:
        self.memes = [m for m in self.memes if m.meme_frame != frame]


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
        text += "memes:\n" + "".join(
            f"  - {{meme_ts: {m.meme_ts:.3f}, meme_frame: {m.meme_frame}}}\n" for m in dataset.memes
        )
    else:
        text += "memes: []\n"
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
        memes = [Meme(float(m["meme_ts"]), int(m["meme_frame"])) for m in data.get("memes") or []]
    except (KeyError, TypeError) as exc:
        raise DatasetError(f"{path}: malformed dataset ({exc!r})") from exc
    frames = [m.meme_frame for m in memes]
    if frames != sorted(set(frames)):
        raise DatasetError(f"{path}: memes must be sorted by frame with no duplicates")
    return Dataset(video=video, memes=memes, mode=mode)


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
    url: str, format_selector: str, downloads_dir: Path = DOWNLOADS_DIR, proxy: str | None = None
) -> tuple[Path, VideoInfo]:
    """Download one yt-dlp format of `url` to `downloads_dir/<id>_<format_id>.<ext>`.

    `format_selector` is a yt-dlp format string, which for a dataset reload is the recorded
    `format_id`. Returns the file and what it is (frame count read from the downloaded file).
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


def ensure_video(
    dataset: Dataset, downloads_dir: Path = DOWNLOADS_DIR, proxy: str | None = None
) -> Path:
    """The local file of the dataset's exact `format_id`, downloaded if absent, and validated."""
    video = dataset.video
    path = downloaded_path(video.id, video.format_id, video.ext, downloads_dir)
    if not path.is_file():
        path, _ = download_format(video.url, video.format_id, downloads_dir, proxy)
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


def positive_frames(dataset: Dataset, video_path: Path) -> Iterator[tuple[int, float, np.ndarray]]:
    """The marked frames, found by sequential decoding; raises if a frame's timestamp disagrees."""
    expected = {m.meme_frame: m.meme_ts for m in dataset.memes}
    for index, timestamp, frame in iter_frames(video_path, expected.__contains__):
        if abs(timestamp - expected[index]) > _TS_TOLERANCE:
            raise DatasetError(
                f"Frame {index} of {video_path} is at {timestamp:.3f}s, the dataset says "
                f"{expected[index]:.3f}s: not the labeled video"
            )
        yield index, timestamp, frame


def negative_frames(
    dataset: Dataset,
    video_path: Path,
    fps: float = 3.0,
    exclusion_window: float = EXCLUSION_WINDOW_SECONDS,
) -> Iterator[tuple[int, float, np.ndarray]]:
    """Scan-rate frames more than `exclusion_window` seconds from every mark.

    A meme lasts several frames and standard mode marks one, so the frames around a mark are
    neither positive nor safely negative and are left out.
    """
    step = scan_step(video_path, fps)
    marks = np.array([m.meme_ts for m in dataset.memes])
    for index, timestamp, frame in iter_frames(video_path, lambda i: i % step == 0):
        if marks.size and np.abs(marks - timestamp).min() <= exclusion_window:
            continue
        yield index, timestamp, frame
