"""Edge black: how much of the outermost edges is near-black."""

import cv2
import numpy as np

from extract_memes.criteria import criterion
from extract_memes.criteria._common import edges

NEAR_BLACK = 0.05 * 255  # brightness under 5% of the maximum


@criterion("edge_black")
def edge_black(frame: np.ndarray) -> float:
    """Percentage (0-100) of near-black pixels, under 5% brightness, in the outer 5% left and right edges.

    Glitch static is dark with bright streaks and specks, so a card's edges are neither empty nor
    fully black: memes score about 28-49, ordinary frames mostly below 25, a black screen near 100.
    """
    gray = cv2.cvtColor(edges(frame), cv2.COLOR_BGR2GRAY)
    return float((gray < NEAR_BLACK).mean() * 100)
