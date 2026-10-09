"""Margin luma: how bright the margins are."""

import numpy as np

from extract_memes.criteria import criterion
from extract_memes.criteria._common import margins


@criterion("margin_luma")
def margin_luma(frame: np.ndarray) -> float:
    """Median brightness of the left and right margins. Glitch static is dark; real scenes are brighter."""
    return float(np.median(margins(frame).mean(axis=2)))
