"""Band: how much brighter the brightest row of the margins is than a typical row."""

import cv2
import numpy as np

from extract_memes.criteria import criterion
from extract_memes.criteria._common import margins


@criterion("band")
def band(frame: np.ndarray) -> float:
    """Brightest row's mean brightness minus the median row brightness, in the left and right margins.

    A glitch card's static is crossed by bright horizontal streaks, which this picks up.
    """
    row_means = cv2.cvtColor(margins(frame), cv2.COLOR_BGR2GRAY).mean(axis=1)
    return max(0.0, float((row_means - np.median(row_means)).max()))
