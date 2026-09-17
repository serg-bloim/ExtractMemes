from unittest import mock

import numpy as np
import pytest

from extract_memes.batch_cleaner import DEFAULT_METHOD, METHODS, banding_score, combine

# `darkest` assumes bands only ever brighten, so it's tested on its own below.
MERGING_METHODS = [method for method in METHODS if method not in ("best_single", "darkest")]


def clean_card() -> np.ndarray:
    """A still card on static margins, with structure inside the card to preserve."""
    rng = np.random.default_rng(0)
    frame = rng.integers(0, 120, (144, 256, 3), dtype=np.uint8)
    frame[20:124, 64:192] = 200
    frame[40:60, 80:176] = 40
    return frame


def glitched(clean: np.ndarray, call: int) -> np.ndarray:
    """The card with a bright and a dark band, at rows that no other call reuses."""
    frame = clean.astype(np.int16)
    top = call * 13
    frame[top : top + 9] += 90
    frame[top + 60 : top + 69] -= 60
    frame += call  # the brightness drift a real batch has
    return np.clip(frame, 0, 255).astype(np.uint8)


def batch(clean: np.ndarray, size: int = 10) -> list[np.ndarray]:
    return [glitched(clean, call) for call in range(size)]


def error(image: np.ndarray, clean: np.ndarray) -> float:
    return float(np.abs(image.astype(np.float32) - clean.astype(np.float32)).mean())


@pytest.mark.parametrize("method", MERGING_METHODS)
def test_combining_beats_every_input_frame(method):
    clean = clean_card()
    frames = batch(clean)

    combined = combine(frames, method)

    assert error(combined, clean) < min(error(frame, clean) for frame in frames)


@pytest.mark.parametrize("method", ["median", "trimmed_mean"])
def test_bands_that_never_collide_are_removed_completely(method):
    # Each row is banded in at most one of the ten frames, so the outliers are always a minority.
    clean = clean_card()

    combined = combine(batch(clean), method).astype(np.float32)
    # Normalisation leaves the batch at its median brightness, not the clean card's, so compare
    # the images without that constant offset.
    combined += clean.astype(np.float32).mean() - combined.mean()

    assert error(combined, clean) <= 1.0


def brightened(clean: np.ndarray, call: int) -> np.ndarray:
    """The card with a bright band only, the kind of distortion `darkest` is meant for."""
    frame = clean.astype(np.int16)
    frame[call * 13 : call * 13 + 9] += 90
    frame += call
    return np.clip(frame, 0, 255).astype(np.uint8)


@pytest.mark.parametrize("method", ["darkest", "darkest_mean"])
def test_darkest_removes_bands_that_only_brighten(method):
    clean = clean_card()
    frames = [brightened(clean, call) for call in range(10)]

    combined = combine(frames, method, normalise=False).astype(np.float32)
    combined += clean.astype(np.float32).mean() - combined.mean()

    assert error(combined, clean) < min(error(frame, clean) for frame in frames)


def test_darkest_keeps_a_band_that_darkens():
    # The documented failure: taking the minimum treats a dark band as the true colour.
    clean = clean_card()
    frames = batch(clean)  # these have a dark band as well as a bright one

    darkest = combine(frames, "darkest")

    assert error(darkest, clean) > error(combine(frames, "trimmed_mean"), clean)


def letterboxed_card() -> np.ndarray:
    """A card with black bars down both sides, as a vertical video in a 16:9 frame has."""
    rng = np.random.default_rng(1)
    frame = np.zeros((144, 256, 3), dtype=np.uint8)
    frame[:, 64:192] = rng.integers(150, 210, (144, 128, 3), dtype=np.uint8)
    return frame


def noisy_band(clean: np.ndarray, call: int, rows: int = 12) -> np.ndarray:
    """One frame with a colourful noise band that also lifts the black bars, as the real ones do."""
    rng = np.random.default_rng(100 + call)
    frame = clean.astype(np.int16)
    top = call * 13
    frame[top : top + rows] += rng.integers(30, 120, (rows, 256, 3))
    return np.clip(frame, 0, 255).astype(np.uint8)


def test_clean_rows_rejects_bands_using_the_black_bars():
    clean = letterboxed_card()
    frames = [noisy_band(clean, call) for call in range(10)]

    combined = combine(frames, "clean_rows", normalise=False)

    assert error(combined, clean) < min(error(frame, clean) for frame in frames)
    # Every row is clean in nine of the ten frames, so the damage never survives selection.
    assert error(combined, clean) < 1.0


def test_clean_rows_falls_back_to_the_least_affected_rows():
    clean = letterboxed_card()
    # Rows 0-11 are banded in every frame, so no row there is ever "good".
    frames = [noisy_band(clean, 0, rows=12) for _ in range(5)]
    frames[2] = clean.copy()
    frames[2][:12] = np.clip(clean[:12].astype(np.int16) + 10, 0, 255).astype(np.uint8)

    combined = combine(frames, "clean_rows", normalise=False)

    assert np.isfinite(combined).all()
    # The least affected frame dominates the rows that are damaged everywhere.
    assert error(combined[:12], clean[:12]) < error(frames[0][:12], clean[:12])


def test_best_single_returns_the_least_banded_input():
    clean = clean_card()
    frames = batch(clean)
    frames.insert(4, clean)  # the only frame with no band at all

    combined = combine(frames, "best_single")

    assert np.array_equal(combined, clean)


def test_banding_score_is_higher_for_a_banded_frame():
    clean = clean_card()

    assert banding_score(glitched(clean, 3)) > banding_score(clean)


def test_flatten_rows_flattens_a_band_the_merge_could_not_remove():
    # A band present in most frames survives the merge, because it is no longer an outlier.
    frames = [glitched(clean_card(), call) for call in [2, 2, 2, 2, 2, 2, 7, 8, 9, 1]]

    kept = combine(frames, DEFAULT_METHOD)
    flattened = combine(frames, DEFAULT_METHOD, flatten_rows=True)

    assert banding_score(flattened) < banding_score(kept)


@pytest.mark.parametrize("method", METHODS)
def test_shape_dtype_and_determinism(method):
    frames = batch(clean_card())

    combined = combine(frames, method)

    assert combined.shape == frames[0].shape
    assert combined.dtype == np.uint8
    assert np.array_equal(combined, combine(frames, method))


def test_one_frame_batch_is_returned_unchanged():
    frame = clean_card()

    combined = combine([frame])

    assert np.array_equal(combined, frame)
    assert combined is not frame


def test_combining_writes_no_file():
    frames = batch(clean_card())

    with mock.patch("cv2.imwrite", side_effect=AssertionError("wrote a file")):
        combine(frames, DEFAULT_METHOD)


def test_empty_batch_raises():
    with pytest.raises(ValueError, match="empty batch"):
        combine([])


def test_mismatched_shapes_raise():
    frames = batch(clean_card())
    frames[3] = frames[3][:100]

    with pytest.raises(ValueError, match="same shape"):
        combine(frames)


def test_unknown_method_raises_naming_the_valid_ones():
    with pytest.raises(ValueError, match="trimmed_mean"):
        combine(batch(clean_card()), "average")
