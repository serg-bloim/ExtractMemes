"""Classify frame images as memes or not with a hand-built image heuristic (see ADR 008)."""

from dataclasses import dataclass

import numpy as np

from extract_memes import criteria
from extract_memes.rule_classifier import Condition, RuleClassifier


@dataclass(frozen=True)
class FrameScores:
    """How much a frame's left and right strips look like a glitch card's surroundings.

    Only `edge_histogram` decides whether a frame is a card; `band` and `texture` are kept for diagnostics.
    """

    band: float  # brightest row's mean brightness minus the median row brightness
    texture: float  # mean saturation change between vertically adjacent pixels
    edge_histogram: float  # distance of the edges' brightness histogram from the memes' average (low = card)


class HeuristicClassifier(RuleClassifier):
    """Flags glitch-framed meme cards: edges whose brightness distribution looks like a card's.

    The scores come from the criteria in `extract_memes.criteria`, the same code anything else that
    lists criteria uses; this class is only the rule `edge_histogram < threshold`.
    """

    def __init__(self, edge_histogram_threshold: float = 2.1) -> None:
        self.edge_histogram_threshold = edge_histogram_threshold
        super().__init__(Condition("edge_histogram", "<", edge_histogram_threshold))

    @staticmethod
    def scores(frame: np.ndarray) -> FrameScores:
        """Score the strips left and right of where a card would sit in a BGR frame."""
        return FrameScores(
            band=criteria.get("band").score(frame),
            texture=criteria.get("texture").score(frame),
            edge_histogram=criteria.get("edge_histogram").score(frame),
        )
