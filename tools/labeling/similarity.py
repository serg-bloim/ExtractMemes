"""Finding the frames next to a selection that belong to the same shot.

Comparing each frame with the selected one doesn't work for the glitch-framed meme cards: the card
animates, so frames inside one differ from each other about as much as from the scene around it.
What does separate them is the step between neighbouring frames: inside a card (or any continuous
shot) it is small or steady, while at the card's edges it jumps (measured on FtU4MuksCzE at 32x18
grayscale: 13..26 inside the cards, 55..100 at their edges). So the selection grows outward while
the frame-to-frame step stays under a cut threshold.
"""

from collections.abc import Callable

import cv2
import numpy as np

SIZE = (32, 18)
CUT_THRESHOLD = 40.0  # mean absolute difference (0..255) between neighbours above which it is a cut
MAX_SECONDS = 3.0     # how far one side may grow


def descriptor(frame: np.ndarray) -> np.ndarray:
    """A frame shrunk to a small grayscale thumbnail; enough to see a cut or a card appearing."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    return cv2.resize(gray, SIZE, interpolation=cv2.INTER_AREA).astype(np.float32)


def step(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.abs(a - b).mean())


def expand(
    first: int,
    last: int,
    frame_count: int,
    describe: Callable[[int], np.ndarray],
    max_frames: int,
    threshold: float = CUT_THRESHOLD,
) -> tuple[int, int]:
    """Grow `first..last` frame by frame to either side while the step to the next frame is at most
    `threshold`, by at most `max_frames` per side. `describe(i)` gives frame i's descriptor."""
    lo, hi = first, last
    while lo > 0 and first - lo < max_frames and step(describe(lo - 1), describe(lo)) <= threshold:
        lo -= 1
    while hi < frame_count - 1 and hi - last < max_frames and step(describe(hi), describe(hi + 1)) <= threshold:
        hi += 1
    return lo, hi
