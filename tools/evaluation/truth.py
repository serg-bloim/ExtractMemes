"""Ground truth for the scanned frames of a labeled video: positive, negative or ignored."""

import numpy as np

from tools.labeling.dataset import Dataset

POSITIVE, NEGATIVE, IGNORED = 1, 0, -1
IGNORE_WINDOW_SECONDS = 1.0


def ground_truth(
    dataset: Dataset, rows: np.ndarray, pts: np.ndarray, ignore_window: float = IGNORE_WINDOW_SECONDS
) -> np.ndarray:
    """The label of each scanned frame (`rows` are frame indices, `pts` the timestamp of every frame).

    A frame inside a meme's start..end window is positive; every other frame is negative, and an
    explicit not-meme frame is negative even inside a window. A meme marked with a single frame has
    no known extent: its nearest scanned frame is positive and the other scanned frames within
    `ignore_window` seconds of the mark are ignored. A window that holds no scanned frame still
    contributes the scanned frame nearest its anchor, so every meme has a positive.
    """
    times = pts[rows]
    positive = np.zeros(len(rows), dtype=bool)
    ignored = np.zeros(len(rows), dtype=bool)
    for meme in dataset.memes:
        if meme.start_frame is None and meme.end_frame is None:
            ignored |= np.abs(times - pts[meme.meme_frame]) <= ignore_window
        inside = (rows >= meme.first) & (rows <= meme.last)
        if not inside.any():
            inside[int(np.abs(rows - meme.meme_frame).argmin())] = True
        positive |= inside
    labels = np.full(len(rows), NEGATIVE, dtype=np.int8)
    labels[ignored] = IGNORED
    labels[positive] = POSITIVE
    for not_meme in dataset.not_memes:  # explicit negatives override everything
        labels[rows == not_meme.not_meme_frame] = NEGATIVE
    return labels
