"""Classify frame images as memes or not with a hand-built image heuristic (see ADR 008)."""

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from extract_memes.classifier import FrameClassifier

# The thresholds were calibrated on 256x144 scan frames, so every frame is scored at that size.
_WIDTH, _HEIGHT = 256, 144
_MARGIN = _WIDTH // 5


@dataclass(frozen=True)
class FrameScores:
    """How much a frame's left and right margins look like a glitch card's surroundings."""

    band: float  # brightest row's mean brightness minus the median row brightness
    texture: float  # mean saturation change between vertically adjacent pixels


class HeuristicClassifier(FrameClassifier):
    """Flags glitch-framed meme cards: bright horizontal bands crossing multicolored static."""

    def __init__(self, band_threshold: float = 180.0, texture_threshold: float = 18.0) -> None:
        self.band_threshold = band_threshold
        self.texture_threshold = texture_threshold

    @staticmethod
    def scores(frame: np.ndarray) -> FrameScores:
        """Score the strips left and right of where a card would sit in a BGR frame."""
        if frame.shape[:2] != (_HEIGHT, _WIDTH):
            frame = cv2.resize(frame, (_WIDTH, _HEIGHT), interpolation=cv2.INTER_AREA)
        margins = np.hstack([frame[:, :_MARGIN], frame[:, -_MARGIN:]])

        row_means = cv2.cvtColor(margins, cv2.COLOR_BGR2GRAY).mean(axis=1)
        band = max(0.0, float((row_means - np.median(row_means)).max()))

        saturation = cv2.cvtColor(margins, cv2.COLOR_BGR2HSV)[..., 1].astype(np.float32)
        texture = float(np.abs(np.diff(saturation, axis=0)).mean())
        return FrameScores(band=band, texture=texture)

    def is_meme_frame(self, frame: np.ndarray) -> bool:
        scores = self.scores(frame)
        return scores.band > self.band_threshold and scores.texture > self.texture_threshold

    def is_meme(self, image_path: Path) -> bool:
        frame = cv2.imread(str(image_path))
        if frame is None:
            raise RuntimeError(f"Could not read image: {image_path}")
        return self.is_meme_frame(frame)
