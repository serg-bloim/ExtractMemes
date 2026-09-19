"""Orchestrate a run: scan a worst-quality copy for memes, then extract them from a best-quality copy."""

import math
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs, urlparse

import cv2
import numpy as np
from tqdm import tqdm

from extract_memes import batch_cleaner
from extract_memes.classifier import ClaudeCliClassifier, FrameClassifier
from extract_memes.downloader import download, download_sections
from extract_memes.frame_extractor import frames_from, sample_frames
from extract_memes.heuristic_classifier import HeuristicClassifier
from extract_memes.telegram_uploader import TelegramUploader
from extract_memes.uploader import Uploader


MEME_LABEL = "Мем"
"""The title each timecode line carries: YouTube needs a title after the timestamp."""

SECTION_PAD_SECONDS = 0.5
"""Slack on each side of an extraction window, covering the extra frame `count` reaches for."""

SECTION_MERGE_GAP_SECONDS = 10.0
"""Windows this close become one section: every extra section refetches the video's index."""

PARTIAL_MAX_COVERAGE = 0.5
"""Above this share of the video, fetching sections costs more than fetching the whole file."""


def default_run_name(source: str) -> str:
    """Derive a file-system-safe run name from a URL or local path."""
    if "://" in source:
        url = urlparse(source)
        video_ids = parse_qs(url.query).get("v")
        if video_ids:
            base = video_ids[0]
        else:
            segments = [segment for segment in url.path.split("/") if segment]
            base = segments[-1] if segments else url.hostname or ""
    else:
        base = Path(source).stem
    return re.sub(r"[^A-Za-z0-9_-]+", "_", base).strip("_") or "video"


def _frame_name(index: int, timestamp: float) -> str:
    return f"frame_{index:06d}_{timestamp:.2f}s.jpg"


def format_timecode(seconds: float) -> str:
    """Format `seconds` as a YouTube timecode: `M:SS`, or `H:MM:SS` from one hour on.

    Truncated to whole seconds, so a timecode never lands after the moment it names.
    """
    total = max(0, int(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _write_timecodes(run_dir: Path, timecodes: list[str]) -> None:
    """Write one timecode line per meme to `timecodes.txt`, and say where it went."""
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "timecodes.txt"
    path.write_text("".join(f"{line}\n" for line in timecodes), encoding="utf-8")
    print(f"Wrote {len(timecodes)} timecodes to {path}")


def _write_image(path: Path, frame: np.ndarray) -> None:
    if not cv2.imwrite(str(path), frame):
        raise RuntimeError(f"Could not write image: {path}")


def _native_fps(video_path: Path) -> float:
    """Return the video's frame rate, or 25.0 when the file doesn't report one."""
    cap = cv2.VideoCapture(str(video_path))
    try:
        return cap.get(cv2.CAP_PROP_FPS) or 25.0
    finally:
        cap.release()


def _video_duration(video_path: Path) -> float:
    """Return the video's length in seconds, or 0.0 when the file doesn't report one.

    Only used to decide whether partial downloading is worth it, so the frame count's usual
    unreliability costs nothing worse than a suboptimal choice.
    """
    cap = cv2.VideoCapture(str(video_path))
    try:
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        fps = cap.get(cv2.CAP_PROP_FPS)
        return frames / fps if frames > 0 and fps > 0 else 0.0
    finally:
        cap.release()


def section_ranges(
    timestamps: Sequence[float],
    window_seconds: float,
    pad: float = SECTION_PAD_SECONDS,
    gap: float = SECTION_MERGE_GAP_SECONDS,
) -> list[tuple[int, int]]:
    """Merge each timestamp's extraction window into as few whole-second ranges as possible.

    A window runs `2 * window_seconds` from `timestamp - window_seconds`, clamped at zero -- so a
    timestamp near the start of the video keeps its full width and reaches further to the right.
    Each range covers that, plus `pad` on each side, widened to whole seconds. Two ranges merge
    when they overlap or sit within `gap` of each other: at the scan rate one meme card flags
    several frames in a row, and sections are what costs, not windows.
    """
    windows = sorted(
        (
            max(0, math.floor(start - pad)),
            math.ceil(start + 2 * window_seconds + pad),
        )
        for start in (max(0.0, timestamp - window_seconds) for timestamp in timestamps)
    )
    merged: list[tuple[int, int]] = []
    for start, end in windows:
        if merged and start - merged[-1][1] <= gap:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _to_scan_size(frame: np.ndarray, scan_shape: tuple[int, int]) -> np.ndarray:
    """Downscale a best-quality frame to the scan resolution the classifier was given."""
    if frame.shape[:2] == scan_shape:
        return frame
    height, width = scan_shape
    return cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)


def _window_size(
    video_path: Path, window_seconds: float, cache: dict[Path, tuple[float, int]]
) -> tuple[float, int]:
    """Return `(native_fps, frames_per_window)` for `video_path`, opening each file only once."""
    if video_path not in cache:
        fps = _native_fps(video_path)
        cache[video_path] = (fps, round(2 * window_seconds * fps) + 1)
    return cache[video_path]


def _extraction_sources(
    source: str,
    timestamps: Sequence[float],
    downloads_dir: Path,
    window_seconds: float,
    scan_path: Path,
    proxy: str | None,
    full_download: bool,
) -> list[tuple[Path, float]]:
    """Return the best-quality video to read each timestamp from, and where that video starts.

    By default a URL source is fetched as sections covering just the extraction windows, and the
    offset is the section's start in the whole video. A local file, `full_download=True`, memes
    dense enough that sections would cover most of the video, or a section download that fails all
    give the whole file back with an offset of zero.
    """

    def whole_video(reason: str = "") -> list[tuple[Path, float]]:
        if reason:
            print(f"{reason}; downloading the whole video instead.")
        return [(download(source, "best", downloads_dir, proxy=proxy), 0.0)] * len(timestamps)

    if full_download or Path(source).is_file():
        return whole_video()

    ranges = section_ranges(timestamps, window_seconds)
    duration = _video_duration(scan_path)
    covered = sum(end - start for start, end in ranges)
    if duration and covered > PARTIAL_MAX_COVERAGE * duration:
        return whole_video(f"Memes cover {covered:.0f}s of {duration:.0f}s")
    try:
        sections = download_sections(source, ranges, downloads_dir, proxy=proxy)
        if len(sections) != len(ranges):
            raise RuntimeError(f"asked for {len(ranges)} sections, got {len(sections)}")
        return [sections[_range_index(timestamp, ranges)] for timestamp in timestamps]
    except RuntimeError as exc:
        return whole_video(f"Partial download failed ({exc})")


def _range_index(timestamp: float, ranges: Sequence[tuple[int, int]]) -> int:
    """Index of the range covering `timestamp`, which `section_ranges` guarantees exists."""
    for index, (start, end) in enumerate(ranges):
        if start <= timestamp <= end:
            return index
    raise RuntimeError(f"no downloaded section covers {timestamp}s")


def run(
    source: str,
    downloads_dir: Path = Path("downloads"),
    runtime_dir: Path = Path(".runtime"),
    run_name: str | None = None,
    fps: float = 2.0,
    classifier: FrameClassifier | None = None,
    classifier_model: str = "claude-haiku-4-5-20251001",
    classifier_effort: str | None = "low",
    classifier_type: Literal["heuristic", "claude"] = "heuristic",
    save_frames: bool = False,
    save_low_res: bool = False,
    window_seconds: float = 1.0,
    clean_method: str | None = batch_cleaner.DEFAULT_METHOD,
    save_high_res: bool = False,
    save_timecodes: bool = False,
    timecode_offset: float = 0.0,
    no_images: bool = False,
    uploader: Uploader | None = None,
    upload_to: Literal["telegram"] | None = None,
    telegram_bot_token: str | None = None,
    telegram_chat_id: str | None = None,
    proxy: str | None = None,
    full_download: bool = False,
) -> list[Path]:
    """Extract the memes in `source` and return one cleaned image path per meme, in video order.

    Sampled frames are kept in memory. With `save_frames=True`, they are written to
    `<runtime_dir>/<run_name>/frames/`. Flagged frames are written to `low-res/` when
    `save_low_res=True`.

    Each flagged timestamp becomes one batch: every best-quality frame within `window_seconds`
    either side of it is downscaled to the scan resolution and given to the classifier, and the
    frames that also look like memes are combined into `clean/meme_<n:03d>.png` with `clean_method`
    (one of `batch_cleaner.METHODS`), which removes most of the glitch bands.

    With `save_timecodes=True`, `timecodes.txt` lists the start of each meme — the earliest
    batch frame, shifted by `timecode_offset` seconds and clamped at zero — as `<timecode> Meme <n>`.

    With `no_images=True` the run ends after the scan: no best-quality copy is downloaded and no
    image is written, so the timecodes are the scan timestamps of the flagged frames and `[]` is
    returned. `clean_method` is then ignored.

    The batch frames themselves are kept only with `save_high_res=True`, which writes them to
    `high-res/meme_<n:03d>/`. With `clean_method=None` nothing is cleaned and those frames are
    returned instead, so that combination requires `save_high_res=True`.

    With `uploader` set (or `upload_to="telegram"`, which builds a `TelegramUploader` from
    `telegram_bot_token`/`telegram_chat_id`), `uploader.upload_all(saved, source)` is called once
    before `run` returns. A failure there is logged and does not abort the run or affect what's
    returned — unlike every other step here, whose errors propagate.

    The best-quality pass fetches only the windows it reads. `full_download=True` fetches the whole
    file instead, as do a local-file source and the fallbacks in `_extraction_sources`; either way
    the frames, their names and the timecodes come out the same.
    """
    if classifier is None:
        if classifier_type == "heuristic":
            classifier = HeuristicClassifier()
        elif classifier_type == "claude":
            classifier = ClaudeCliClassifier(model=classifier_model, effort=classifier_effort)
        else:
            raise ValueError(f"classifier_type must be 'heuristic' or 'claude', not {classifier_type!r}")
    if clean_method is not None and clean_method not in batch_cleaner.METHODS:
        raise ValueError(f"clean_method must be None or one of {batch_cleaner.METHODS}, not {clean_method!r}")
    if uploader is None and upload_to == "telegram":
        uploader = TelegramUploader(bot_token=telegram_bot_token, chat_id=telegram_chat_id)
    if no_images:
        if save_high_res:
            raise ValueError("no_images and save_high_res contradict each other")
        if uploader is not None:
            raise ValueError("no_images and uploading contradict each other: there is nothing to upload")
        if not (save_timecodes or save_low_res or save_frames):
            raise ValueError(
                "nothing would be saved: with no_images, pass save_timecodes=True, "
                "save_low_res=True, or save_frames=True"
            )
    elif clean_method is None and not save_high_res:
        raise ValueError("nothing would be saved: pass a clean_method, or save_high_res=True")
    run_dir = runtime_dir / (run_name or default_run_name(source))
    frames_dir = run_dir / "frames"
    high_res_dir = run_dir / "high-res"
    low_res_dir = run_dir / "low-res"
    clean_dir = run_dir / "clean"
    if save_frames:
        frames_dir.mkdir(parents=True, exist_ok=True)
    if save_high_res:
        high_res_dir.mkdir(parents=True, exist_ok=True)
    if save_low_res:
        low_res_dir.mkdir(parents=True, exist_ok=True)
    if clean_method is not None and not no_images:
        clean_dir.mkdir(parents=True, exist_ok=True)

    scan_path = download(source, "worst", downloads_dir, proxy=proxy)
    flagged: list[tuple[int, float]] = []
    scan_shape = (0, 0)
    for index, timestamp, frame in tqdm(sample_frames(scan_path, fps=fps), desc="Scanning frames"):
        scan_shape = frame.shape[:2]
        if save_frames:
            frame_path = frames_dir / _frame_name(index, timestamp)
            _write_image(frame_path, frame)
        if classifier.is_meme_frame(frame):
            flagged.append((index, timestamp))
            if save_low_res:
                _write_image(low_res_dir / _frame_name(index, timestamp), frame)

    if not flagged:
        print("No memes found.")
        return []

    if no_images:
        if save_timecodes:
            _write_timecodes(
                run_dir,
                [
                    f"{format_timecode(timestamp + timecode_offset)} {MEME_LABEL} {meme_number}"
                    for meme_number, (_, timestamp) in enumerate(flagged, start=1)
                ],
            )
        return []

    sources = _extraction_sources(
        source,
        [timestamp for _, timestamp in flagged],
        downloads_dir,
        window_seconds,
        scan_path,
        proxy,
        full_download,
    )
    window_cache: dict[Path, tuple[float, int]] = {}
    saved: list[Path] = []
    timecodes: list[str] = []
    for meme_number, (_, timestamp) in enumerate(tqdm(flagged, desc="Extracting memes"), start=1):
        meme_dir = high_res_dir / f"meme_{meme_number:03d}"
        if save_high_res:
            meme_dir.mkdir(parents=True, exist_ok=True)
        extract_path, offset = sources[meme_number - 1]
        native_fps, count = _window_size(extract_path, window_seconds, window_cache)
        first_frame = max(0, round((timestamp - window_seconds) * native_fps))
        section_frame = round(offset * native_fps)
        # Aim at the middle of that frame: a seek that lands exactly on a frame boundary can go
        # either way, and subtracting a section's start moves the boundary by a float hair, which
        # would shift a section run's frames one place against a whole-file run's.
        start = (max(0, first_frame - section_frame) + 0.5) / native_fps
        batch: list[np.ndarray] = []
        batch_start = 0.0
        for index, frame_timestamp, frame in frames_from(extract_path, start, count):
            # Back to positions in the whole video, so a section run names its frames and writes
            # its timecodes exactly like a full-file run.
            index += section_frame
            frame_timestamp += offset
            if not classifier.is_meme_frame(_to_scan_size(frame, scan_shape)):
                continue
            if not batch:
                batch_start = frame_timestamp
            batch.append(frame)
            if save_high_res:
                meme_path = meme_dir / _frame_name(index, frame_timestamp)
                _write_image(meme_path, frame)
                if clean_method is None:
                    saved.append(meme_path)
        if batch:
            timecodes.append(f"{format_timecode(batch_start + timecode_offset)} {MEME_LABEL} {meme_number}")
        if clean_method is not None and batch:
            clean_path = clean_dir / f"meme_{meme_number:03d}.png"
            _write_image(clean_path, batch_cleaner.combine(batch, clean_method))
            saved.append(clean_path)
    if save_timecodes:
        _write_timecodes(run_dir, timecodes)
    if uploader is not None:
        try:
            uploader.upload_all(saved, source)
        except Exception as exc:
            print(f"Upload failed: {exc}")
    return saved
