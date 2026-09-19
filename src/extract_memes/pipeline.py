"""Orchestrate a run: scan a worst-quality copy for memes, then extract them from a best-quality copy."""

import re
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs, urlparse

import cv2
import numpy as np
from tqdm import tqdm

from extract_memes import batch_cleaner
from extract_memes.classifier import ClaudeCliClassifier, FrameClassifier
from extract_memes.downloader import download
from extract_memes.frame_extractor import frames_from, sample_frames
from extract_memes.heuristic_classifier import HeuristicClassifier
from extract_memes.telegram_uploader import TelegramUploader
from extract_memes.uploader import Uploader


MEME_LABEL = "Мем"
"""The title each timecode line carries: YouTube needs a title after the timestamp."""


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


def _to_scan_size(frame: np.ndarray, scan_shape: tuple[int, int]) -> np.ndarray:
    """Downscale a best-quality frame to the scan resolution the classifier was given."""
    if frame.shape[:2] == scan_shape:
        return frame
    height, width = scan_shape
    return cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)


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

    extract_path = download(source, "best", downloads_dir, proxy=proxy)
    count = round(2 * window_seconds * _native_fps(extract_path)) + 1
    saved: list[Path] = []
    timecodes: list[str] = []
    for meme_number, (_, timestamp) in enumerate(tqdm(flagged, desc="Extracting memes"), start=1):
        meme_dir = high_res_dir / f"meme_{meme_number:03d}"
        if save_high_res:
            meme_dir.mkdir(parents=True, exist_ok=True)
        start = max(0.0, timestamp - window_seconds)
        batch: list[np.ndarray] = []
        batch_start = 0.0
        for index, frame_timestamp, frame in frames_from(extract_path, start, count):
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
