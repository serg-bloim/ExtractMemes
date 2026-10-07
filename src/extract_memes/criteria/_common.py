"""What the criteria share: the scan size they are measured at and the strips beside a card."""

import cv2
import numpy as np

# The thresholds were calibrated on 256x144 scan frames, so every frame is scored at that size.
SCAN_WIDTH, SCAN_HEIGHT = 256, 144
MARGIN_WIDTH = SCAN_WIDTH // 5


def scan_size(frame: np.ndarray) -> np.ndarray:
    """`frame` (BGR) at the scan size, so a score doesn't depend on the video's resolution."""
    if frame.shape[:2] != (SCAN_HEIGHT, SCAN_WIDTH):
        frame = cv2.resize(frame, (SCAN_WIDTH, SCAN_HEIGHT), interpolation=cv2.INTER_AREA)
    return frame


def margins(frame: np.ndarray) -> np.ndarray:
    """The strips left and right of where a card would sit, side by side (BGR, scan size)."""
    frame = scan_size(frame)
    return np.hstack([frame[:, :MARGIN_WIDTH], frame[:, -MARGIN_WIDTH:]])
