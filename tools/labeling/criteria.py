"""The registry of classifier criteria the labeler shows and filters on.

A criterion is a name, a function from a BGR frame to a number, and an optional threshold (shown as
a guide; the verdict comes from `VERDICT`). To try a new idea, add one function and one `Criterion`
to `CRITERIA`; the labeler recomputes only that criterion's cached scores (see index.py).
"""

import inspect
from collections.abc import Callable
from dataclasses import dataclass

import cv2
import numpy as np

from extract_memes.heuristic_classifier import HeuristicClassifier

_WIDTH, _HEIGHT = 256, 144
_MARGIN = _WIDTH // 5


@dataclass(frozen=True)
class Criterion:
    name: str
    score: Callable[[np.ndarray], float]
    threshold: float | None = None

    def source_hash(self) -> str:
        """Changes when the scoring function's source does, which invalidates the cached scores."""
        import hashlib

        return hashlib.sha1(inspect.getsource(self.score).encode()).hexdigest()[:12]


def _margins(frame: np.ndarray) -> np.ndarray:
    """The left and right fifths of the frame at scan size, side by side (BGR)."""
    if frame.shape[:2] != (_HEIGHT, _WIDTH):
        frame = cv2.resize(frame, (_WIDTH, _HEIGHT), interpolation=cv2.INTER_AREA)
    return np.hstack([frame[:, :_MARGIN], frame[:, -_MARGIN:]])


def band(frame: np.ndarray) -> float:
    return HeuristicClassifier.scores(frame).band


def texture(frame: np.ndarray) -> float:
    return HeuristicClassifier.scores(frame).texture


def margin_luma(frame: np.ndarray) -> float:
    """Median brightness of the side margins. Glitch static is dark; real scenes are brighter."""
    return float(np.median(_margins(frame).mean(axis=2)))


def hue_consistency(frame: np.ndarray) -> float:
    """1 when the margins' coloured pixels share one hue, near 0 when every hue is mixed (static)."""
    hsv = cv2.cvtColor(_margins(frame), cv2.COLOR_BGR2HSV)
    coloured = (hsv[..., 1] > 40) & (hsv[..., 2] > 30)
    if coloured.sum() <= 50:
        return 1.0
    angle = hsv[..., 0][coloured].astype(np.float32) * np.pi / 90  # OpenCV hue is 0-179
    return float(np.hypot(np.cos(angle).mean(), np.sin(angle).mean()))


CRITERIA: list[Criterion] = [
    Criterion("band", band, threshold=180.0),
    Criterion("texture", texture),
    Criterion("margin_luma", margin_luma),
    Criterion("hue_consistency", hue_consistency),
]


def verdict(frame: np.ndarray) -> bool:
    """The production classifier's decision for a frame."""
    return HeuristicClassifier().is_meme_frame(frame)


def verdict_hash() -> str:
    import hashlib

    source = inspect.getsource(HeuristicClassifier)
    return hashlib.sha1(source.encode()).hexdigest()[:12]
