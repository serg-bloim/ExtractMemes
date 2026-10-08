"""Helpers for the labeling-tool tests: a tiny synthetic video whose frames can be told apart."""

from pathlib import Path

import cv2
import numpy as np

FPS = 25.0
SIZE = (128, 72)  # width, height


def make_video(path: Path, frames: int = 75) -> Path:
    """An mp4 where frame i is a flat colour that depends on i, so a decoded frame names its index."""
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, SIZE)
    assert writer.isOpened()
    for i in range(frames):
        frame = np.zeros((SIZE[1], SIZE[0], 3), np.uint8)
        frame[:] = (i * 3 % 256, 255 - i * 3 % 256, 40)
        writer.write(frame)
    writer.release()
    return path


def make_video_with_cuts(path: Path, cuts=(25, 50), frames: int = 75) -> Path:
    """Like `make_video`, but the picture jumps between very different brightnesses at the `cuts`,
    so the frames fall into rows (runs of similar frames) that start at 0 and at each cut."""
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, SIZE)
    assert writer.isOpened()
    levels = [30, 220, 90, 250]
    for i in range(frames):
        segment = sum(i >= c for c in cuts)
        frame = np.full((SIZE[1], SIZE[0], 3), levels[segment % len(levels)], np.uint8)
        writer.write(frame)
    writer.release()
    return path
