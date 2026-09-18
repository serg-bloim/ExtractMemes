"""Read frames from a video file: regular sampling, a run of frames, or one frame at a timestamp."""

from collections.abc import Iterator
from pathlib import Path

import cv2
import numpy as np


def _open(video_path: Path) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        cap.release()
        raise RuntimeError(f"Could not open video file: {video_path}")
    return cap


def sample_frames(video_path: Path, fps: float = 2.0) -> Iterator[tuple[int, float, np.ndarray]]:
    """Yield `(frame_index, timestamp_seconds, frame)` for every `step`-th decoded frame.

    `step = max(1, round(native_fps / fps))`, so the effective rate is `native_fps / step`, which
    isn't always exactly `fps` (25 fps at `fps=2.0` gives step 12). Frames are BGR, as decoded.
    """
    cap = _open(video_path)
    try:
        native_fps = cap.get(cv2.CAP_PROP_FPS) or fps
        step = max(1, round(native_fps / fps))
        # Decode sequentially until the first failed read; CAP_PROP_FRAME_COUNT is unreliable.
        frame_index = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                return
            if frame_index % step == 0:
                yield frame_index, frame_index / native_fps, frame
            frame_index += 1
    finally:
        cap.release()


def frames_from(
    video_path: Path, start_seconds: float, count: int
) -> Iterator[tuple[int, float, np.ndarray]]:
    """Yield up to `count` consecutive `(frame_index, timestamp_seconds, frame)` from `start_seconds`.

    The file is opened and sought once, so the frames after the first cost only a decode each.
    The index comes from the capture, because the seek lands on the nearest decodable frame, which
    can be a little before `start_seconds`. The timestamp is `frame_index / native_fps`, as in
    `sample_frames`; `CAP_PROP_POS_MSEC` isn't used because it can lag `CAP_PROP_POS_FRAMES` by a
    frame. Stops early at the first failed read, so a `start_seconds` past the end yields nothing.
    """
    cap = _open(video_path)
    try:
        native_fps = cap.get(cv2.CAP_PROP_FPS)
        cap.set(cv2.CAP_PROP_POS_MSEC, start_seconds * 1000)
        for _ in range(count):
            frame_index = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
            timestamp = frame_index / native_fps if native_fps else cap.get(cv2.CAP_PROP_POS_MSEC) / 1000
            ok, frame = cap.read()
            if not ok:
                return
            yield frame_index, timestamp, frame
    finally:
        cap.release()


def frame_at(video_path: Path, timestamp_seconds: float) -> np.ndarray:
    """Return the BGR frame at `timestamp_seconds`, seeking by time."""
    cap = _open(video_path)
    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, timestamp_seconds * 1000)
        ok, frame = cap.read()
        if not ok:
            raise RuntimeError(f"Could not read a frame at {timestamp_seconds}s from {video_path}")
        return frame
    finally:
        cap.release()
