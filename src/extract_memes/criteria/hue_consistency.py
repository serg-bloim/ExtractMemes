"""Hue consistency: whether the margins' colours are one hue or a mix."""

import cv2
import numpy as np

from extract_memes.criteria import criterion
from extract_memes.criteria._common import margins


@criterion("hue_consistency")
def hue_consistency(frame: np.ndarray) -> float:
    """1 when the margins' coloured pixels share one hue, near 0 when every hue is mixed (static)."""
    hsv = cv2.cvtColor(margins(frame), cv2.COLOR_BGR2HSV)
    coloured = (hsv[..., 1] > 40) & (hsv[..., 2] > 30)
    if coloured.sum() <= 50:
        return 1.0
    angle = hsv[..., 0][coloured].astype(np.float32) * np.pi / 90  # OpenCV hue is 0-179
    return float(np.hypot(np.cos(angle).mean(), np.sin(angle).mean()))
