"""Ground truth for the scanned frames of a labeled video: positive, negative or ignored."""

import numpy as np

from tools.labeling.dataset import Dataset

POSITIVE, NEGATIVE, IGNORED = 1, 0, -1
IGNORE_WINDOW_SECONDS = 1.0


def ground_truth(
    dataset: Dataset, rows: np.ndarray, pts: np.ndarray, ignore_window: float = IGNORE_WINDOW_SECONDS
) -> tuple[np.ndarray, np.ndarray]:
    """`(labels, windows)`: the label of each scanned frame and, for a positive one, its meme's number.

    The meme number (`windows`, -1 for a frame in no meme) groups the positive frames of one meme, so
    a rule can be judged per meme (was any of its frames detected?) as well as per frame.

    The label of each scanned frame (`rows` are frame indices, `pts` the timestamp of every frame).

    A frame inside a meme's start..end window is positive; every other frame is negative, and an
    explicit not-meme frame is negative even inside a window. A meme marked with a single frame has
    no known extent: its nearest scanned frame is positive and the other scanned frames within
    `ignore_window` seconds of the mark are ignored. A window that holds no scanned frame still
    contributes the scanned frame nearest its anchor, so every meme has a positive.
    """
    times = pts[rows]
    windows = np.full(len(rows), -1, dtype=np.int32)
    ignored = np.zeros(len(rows), dtype=bool)
    for number, meme in enumerate(dataset.memes):
        if meme.start_frame is None and meme.end_frame is None:
            ignored |= np.abs(times - pts[meme.meme_frame]) <= ignore_window
        inside = (rows >= meme.first) & (rows <= meme.last)
        if not inside.any():
            inside[int(np.abs(rows - meme.meme_frame).argmin())] = True
        windows[inside] = number
    labels = np.full(len(rows), NEGATIVE, dtype=np.int8)
    labels[ignored] = IGNORED
    labels[windows >= 0] = POSITIVE
    for not_meme in dataset.not_memes:  # explicit negatives override everything
        hit = rows == not_meme.not_meme_frame
        labels[hit] = NEGATIVE
        windows[hit] = -1
    return labels, windows
