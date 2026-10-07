"""Texture: how much the margins' colour changes from one pixel row to the next."""

import cv2
import numpy as np

from extract_memes.criteria import criterion
from extract_memes.criteria._common import margins


@criterion("texture")
def texture(frame: np.ndarray) -> float:
    """Mean saturation change between vertically adjacent pixels of the left and right margins."""
    saturation = cv2.cvtColor(margins(frame), cv2.COLOR_BGR2HSV)[..., 1].astype(np.float32)
    return float(np.abs(np.diff(saturation, axis=0)).mean())
