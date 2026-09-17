"""Orchestrate a run: scan a worst-quality copy for memes, then extract them from a best-quality copy."""

import re
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs, urlparse

import cv2
import numpy as np
from tqdm import tqdm

from extract_memes.classifier import ClaudeCliClassifier, FrameClassifier
from extract_memes.downloader import download
from extract_memes.frame_extractor import frame_at, sample_frames
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
) -> list[Path]:
    """Extract the memes in `source` and return the best-quality image paths, in video order.

    Sampled frames are kept in memory. With `save_frames=True`, they are written to
    `<runtime_dir>/<run_name>/frames/`. Flagged frames are written to `low-res/` when
    `save_low_res=True`, and always to `high-res/` at the end as best-quality `frame_*` files.
    """
    if classifier is None:
        if classifier_type == "heuristic":
            classifier = HeuristicClassifier()
        elif classifier_type == "claude":
            classifier = ClaudeCliClassifier(model=classifier_model, effort=classifier_effort)
        else:
            raise ValueError(f"classifier_type must be 'heuristic' or 'claude', not {classifier_type!r}")
    run_dir = runtime_dir / (run_name or default_run_name(source))
    frames_dir = run_dir / "frames"
    high_res_dir = run_dir / "high-res"
    low_res_dir = run_dir / "low-res"
    if save_frames:
        frames_dir.mkdir(parents=True, exist_ok=True)
    high_res_dir.mkdir(parents=True, exist_ok=True)
    if save_low_res:
        low_res_dir.mkdir(parents=True, exist_ok=True)

    scan_path = download(source, "worst", downloads_dir)
    flagged: list[tuple[int, float]] = []
    for index, timestamp, frame in tqdm(sample_frames(scan_path, fps=fps), desc="Scanning frames"):
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
    saved: list[Path] = []
    for index, timestamp in tqdm(flagged, desc="Extracting memes"):
        meme_path = high_res_dir / _frame_name(index, timestamp)
        _write_image(meme_path, frame_at(extract_path, timestamp))
        saved.append(meme_path)
    return saved
