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
) -> list[Path]:
    """Extract the memes in `source` and return one cleaned image path per meme, in video order.

    Sampled frames are kept in memory. With `save_frames=True`, they are written to
    `<runtime_dir>/<run_name>/frames/`. Flagged frames are written to `low-res/` when
    `save_low_res=True`.

    Each flagged timestamp becomes one batch under `high-res/meme_<n:03d>/`: every best-quality
    frame within `window_seconds` either side of it is downscaled to the scan resolution, given to
    the classifier, and saved at full quality if it too looks like a meme. The batch is then
    combined into `clean/meme_<n:03d>.png` with `clean_method` (one of `batch_cleaner.METHODS`),
    which removes most of the glitch bands. With `clean_method=None` nothing is cleaned and the
    batch frames are returned instead.
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
    run_dir = runtime_dir / (run_name or default_run_name(source))
    frames_dir = run_dir / "frames"
    high_res_dir = run_dir / "high-res"
    low_res_dir = run_dir / "low-res"
    clean_dir = run_dir / "clean"
    if save_frames:
        frames_dir.mkdir(parents=True, exist_ok=True)
    high_res_dir.mkdir(parents=True, exist_ok=True)
    if save_low_res:
        low_res_dir.mkdir(parents=True, exist_ok=True)
    if clean_method is not None:
        clean_dir.mkdir(parents=True, exist_ok=True)

    scan_path = download(source, "worst", downloads_dir)
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

    extract_path = download(source, "best", downloads_dir)
    count = round(2 * window_seconds * _native_fps(extract_path)) + 1
    saved: list[Path] = []
    for meme_number, (_, timestamp) in enumerate(tqdm(flagged, desc="Extracting memes"), start=1):
        meme_dir = high_res_dir / f"meme_{meme_number:03d}"
        meme_dir.mkdir(parents=True, exist_ok=True)
        start = max(0.0, timestamp - window_seconds)
        batch: list[np.ndarray] = []
        for index, frame_timestamp, frame in frames_from(extract_path, start, count):
            if not classifier.is_meme_frame(_to_scan_size(frame, scan_shape)):
                continue
            meme_path = meme_dir / _frame_name(index, frame_timestamp)
            _write_image(meme_path, frame)
            batch.append(frame)
            if clean_method is None:
                saved.append(meme_path)
        if clean_method is not None and batch:
            clean_path = clean_dir / f"meme_{meme_number:03d}.png"
            _write_image(clean_path, batch_cleaner.combine(batch, clean_method))
            saved.append(clean_path)
    return saved
