"""Combine the frames of one meme batch into a single, less distorted image.

Every frame of a batch shows the same still card, crossed by glitch bands that move vertically from
frame to frame. The frames are geometrically stable, so a per-pixel or per-row temporal combination
is enough to reject most of the distortion; no alignment is needed.
"""

from collections.abc import Sequence

import cv2
import numpy as np

METHODS = (
    "best_single",
    "median",
    "trimmed_mean",
    "consensus",
    "row_pick",
    "darkest",
    "darkest_mean",
    "clean_rows",
)
DEFAULT_METHOD = "clean_rows"

# The card occupies the middle of the frame; the margins are static, so brightness and banding are
# measured on the card columns only.
_CARD_FRACTION = 0.6
# How close two frames must be, in gray levels, to count as agreeing on a pixel's colour.
_CONSENSUS_TOLERANCE = 6.0
# Rows per chunk when combining, to keep the float32 working set small for full-resolution frames.
_CHUNK_ROWS = 256
# How much brighter than the batch's darkest row ends a row may be and still count as undamaged.
_ROW_TOLERANCE = 8.0
# How many rows `clean_rows` averages at minimum, even when every frame's row is damaged.
_ROW_MINIMUM = 3


def _card_columns(width: int) -> tuple[int, int]:
    margin = int(round(width * (1 - _CARD_FRACTION) / 2))
    return margin, width - margin


def banding_score(frame: np.ndarray) -> float:
    """Roughness of the card's row-brightness profile: horizontal bands make it spike."""
    x0, x1 = _card_columns(frame.shape[1])
    row_means = frame[:, x0:x1].astype(np.float32).mean(axis=(1, 2))
    return float(np.abs(np.diff(row_means)).mean())


def _normalised_stack(frames: Sequence[np.ndarray]) -> np.ndarray:
    """Stack the frames as float32 and remove each frame's overall brightness drift."""
    work = np.stack(frames).astype(np.float32)
    x0, x1 = _card_columns(work.shape[2])
    means = work[:, :, x0:x1].mean(axis=(1, 2, 3))
    return work + (float(np.median(means)) - means)[:, None, None, None]


def _median(work: np.ndarray) -> np.ndarray:
    return np.median(work, axis=0)


def _trimmed_mean(work: np.ndarray) -> np.ndarray:
    trim = max(1, len(work) // 5)
    return np.sort(work, axis=0)[trim : len(work) - trim].mean(axis=0)


def _consensus(work: np.ndarray) -> np.ndarray:
    """Average the frames that agree on a pixel; fall back to the median where they don't."""
    median = np.median(work, axis=0)
    agrees = np.abs(work - median) <= _CONSENSUS_TOLERANCE
    count = agrees.sum(axis=0)
    agreed_mean = np.where(agrees, work, 0.0).sum(axis=0) / np.maximum(count, 1)
    # Blend rather than switch: the pixels without a consensus form band-shaped regions, and a hard
    # switch would show their outline.
    enough = max(3, len(work) // 3)
    weight = np.clip((count - 1) / (enough - 1), 0.0, 1.0)
    return weight * agreed_mean + (1 - weight) * median


def _row_pick(work: np.ndarray) -> np.ndarray:
    """Per row, copy the row of the frame that deviates least from the median: no blending."""
    median = np.median(work, axis=0)
    row_deviation = np.abs(work - median).mean(axis=(2, 3))  # (frames, rows)
    # Smooth along rows so a single noisy row doesn't flip the choice back and forth.
    row_deviation = cv2.blur(row_deviation.T, (1, 15)).T
    best = row_deviation.argmin(axis=0)
    return work[best, np.arange(work.shape[1])]


def _darkest(work: np.ndarray) -> np.ndarray:
    """Per pixel, take the frame where it is darkest: a band only ever brightens what it covers.

    The frame is chosen by luminance and its three channels are copied together, so the colour
    stays the one the camera saw instead of a per-channel minimum's colour cast.
    """
    luminance = work @ (0.114, 0.587, 0.299)  # BGR
    darkest = luminance.argmin(axis=0)
    rows, columns = np.indices(darkest.shape)
    return work[darkest, rows, columns]


def _clean_rows(work: np.ndarray) -> np.ndarray:
    """Per row, average the frames whose row ends are closest to black.

    The source is letterboxed, so the far left and right of an undisturbed row are black. Every
    kind of band — bright, or colorful noise — lifts them, which makes the ends a cheap detector
    for "this row of this frame is damaged". Rows within `_ROW_TOLERANCE` of the batch's darkest
    ends are averaged; if a row is damaged in every frame, the least affected are used instead, so
    there is always something to average.
    """
    edge = max(1, work.shape[2] // 20)
    ends = np.concatenate([work[:, :, :edge], work[:, :, -edge:]], axis=2)
    damage = ends.mean(axis=(2, 3))  # (frames, rows): how far the row's ends are from black
    keep = damage <= damage.min(axis=0) + _ROW_TOLERANCE
    # Always average a few rows, so a row that's damaged everywhere still gets its noise averaged.
    rank = damage.argsort(axis=0).argsort(axis=0)
    keep |= rank < min(_ROW_MINIMUM, len(work))
    weights = keep[:, :, None, None]
    return (work * weights).sum(axis=0) / weights.sum(axis=0)


def _darkest_mean(work: np.ndarray) -> np.ndarray:
    """Average the darkest third of the frames per pixel: band-free, without the minimum's bias."""
    order = (work @ (0.114, 0.587, 0.299)).argsort(axis=0)
    keep = max(1, len(work) // 3)
    darkest = np.take_along_axis(work, order[:keep, :, :, None], axis=0)
    return darkest.mean(axis=0)


_COMBINERS = {
    "median": _median,
    "trimmed_mean": _trimmed_mean,
    "consensus": _consensus,
    "row_pick": _row_pick,
    "darkest": _darkest,
    "darkest_mean": _darkest_mean,
    "clean_rows": _clean_rows,
}


def _in_row_chunks(combine_rows, work: np.ndarray) -> np.ndarray:
    """Apply a combiner to horizontal slices, so a full-resolution batch stays in bounded memory."""
    return np.concatenate(
        [combine_rows(work[:, top : top + _CHUNK_ROWS]) for top in range(0, work.shape[1], _CHUNK_ROWS)]
    )


def _flatten_rows(image: np.ndarray) -> np.ndarray:
    """Remove what's left of the bands: a residual band is a row-constant brightness offset."""
    x0, x1 = _card_columns(image.shape[1])
    row_means = image[:, x0:x1].mean(axis=(1, 2))
    baseline = cv2.blur(row_means.reshape(-1, 1), (1, 31)).ravel()
    return image - (row_means - baseline)[:, None, None]


def combine(
    frames: Sequence[np.ndarray],
    method: str = DEFAULT_METHOD,
    *,
    normalise: bool = True,
    flatten_rows: bool = False,
) -> np.ndarray:
    """Combine one batch of BGR frames into a single image of the same shape.

    `method` is one of `METHODS`. `normalise` removes each frame's overall brightness drift first.
    `flatten_rows` additionally subtracts any row-constant brightness left in the result, which also
    flattens genuine wide horizontal structure, so it's off by default.
    """
    if method not in METHODS:
        raise ValueError(f"method must be one of {METHODS}, not {method!r}")
    if not len(frames):
        raise ValueError("cannot combine an empty batch")
    if any(frame.shape != frames[0].shape for frame in frames):
        raise ValueError("every frame of a batch must have the same shape")

    if method == "best_single":
        return min(frames, key=banding_score).copy()
    if len(frames) == 1:
        return np.asarray(frames[0]).copy()

    work = _normalised_stack(frames) if normalise else np.stack(frames).astype(np.float32)
    combined = _in_row_chunks(_COMBINERS[method], work)
    if flatten_rows:
        combined = _flatten_rows(combined)
    return np.clip(combined, 0, 255).astype(np.uint8)
