"""Edge histogram: how far the edges' brightness distribution is from the labeled memes' average."""

import json

import cv2
import numpy as np

from extract_memes.criteria import DATA_DIR, criterion
from extract_memes.criteria._common import edges

BINS = 16
REFERENCE_FILE = "edge_histogram.json"
_loaded: dict[tuple[str, int], tuple[np.ndarray, np.ndarray]] = {}


def features(frame: np.ndarray) -> np.ndarray:
    """The brightness histogram of the left and right edges: `BINS` equal bins over 0-255, summing to 1."""
    gray = cv2.cvtColor(edges(frame), cv2.COLOR_BGR2GRAY)
    counts = np.bincount((gray // (256 // BINS)).ravel(), minlength=BINS)
    return counts / gray.size


def distance(histogram: np.ndarray, mean: np.ndarray, std: np.ndarray) -> float:
    """Root mean square of the per-bin distance from `mean` in units of `std` (with a floor on `std`)."""
    scale = std + 1e-3 * np.abs(mean).mean()
    return float(np.sqrt((((histogram - mean) / scale) ** 2).mean()))


def reference(name: str = REFERENCE_FILE) -> tuple[np.ndarray, np.ndarray]:
    """The memes' mean and standard deviation per bin, read from `criteria/data/` once per file version."""
    path = DATA_DIR / name
    try:
        key = (str(path), path.stat().st_mtime_ns)
    except OSError:
        raise RuntimeError(
            f"Missing reference {path}; build it with `python -m tools.evaluation.build_template edge_histogram`"
        ) from None
    if key not in _loaded:
        try:
            data = json.loads(path.read_text())
            mean, std = np.array(data["mean"], dtype=float), np.array(data["std"], dtype=float)
            if mean.shape != (BINS,) or std.shape != (BINS,):
                raise ValueError(f"expected {BINS} bins")
        except (ValueError, KeyError, TypeError) as exc:
            raise RuntimeError(
                f"Malformed reference {path} ({exc}); rebuild it with "
                "`python -m tools.evaluation.build_template edge_histogram`"
            ) from exc
        _loaded.clear()
        _loaded[key] = (mean, std)
    return _loaded[key]


@criterion("edge_histogram", data=(REFERENCE_FILE,))
def edge_histogram(frame: np.ndarray) -> float:
    """Distance of the outer 5% left/right edges' brightness histogram from the labeled memes' average.

    In units of how much each of the 16 brightness bins varies among memes: memes score about 1-2,
    ordinary frames mostly above 4. The reference is `criteria/data/edge_histogram.json`, built by
    `python -m tools.evaluation.build_template edge_histogram`.
    """
    return distance(features(frame), *reference())
