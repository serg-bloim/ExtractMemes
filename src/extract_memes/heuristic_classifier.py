"""Classify frame images as memes or not with a hand-built image heuristic (see ADR 008)."""

from dataclasses import dataclass

import numpy as np

from extract_memes import criteria
from extract_memes.rule_classifier import Condition, RuleClassifier


@dataclass(frozen=True)
class FrameScores:
    """How much a frame's left and right margins look like a glitch card's surroundings.

    Only `band` decides whether a frame is a card; `texture` is kept for diagnostics.
    """

    band: float  # brightest row's mean brightness minus the median row brightness
    texture: float  # mean saturation change between vertically adjacent pixels


class HeuristicClassifier(RuleClassifier):
    """Flags glitch-framed meme cards: bright horizontal bands in the margins.

    The scores come from the `band` and `texture` criteria in `extract_memes.criteria`, the same
    code anything else that lists criteria uses; this class is only the rule `band > threshold`.
    """

    def __init__(self, band_threshold: float = 180.0) -> None:
        self.band_threshold = band_threshold
        super().__init__(Condition("band", ">", band_threshold))

    @staticmethod
    def scores(frame: np.ndarray) -> FrameScores:
        """Score the strips left and right of where a card would sit in a BGR frame."""
        return FrameScores(band=criteria.get("band").score(frame), texture=criteria.get("texture").score(frame))
