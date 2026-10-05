from pathlib import Path
from unittest import mock

import cv2
import numpy as np
import pytest

from extract_memes.heuristic_classifier import HeuristicClassifier

EXTRA_POSITIVE = Path(__file__).resolve().parent.parent / "sample" / "quick_frame_9-32.png"


def glitch_card(band: bool = True) -> np.ndarray:
    """Dark multicolored noise, a light central card, and (optionally) a white full-width band."""
    frame = np.random.default_rng(0).integers(0, 120, (144, 256, 3), dtype=np.uint8)
    frame[20:124, 64:192] = 230
    if band:
        frame[100:106, :] = 255
    return frame


def test_glitch_card_is_meme():
    assert HeuristicClassifier().is_meme_frame(glitch_card())


def test_static_without_band_is_not_meme():
    assert not HeuristicClassifier().is_meme_frame(glitch_card(band=False))


def test_band_on_flat_background_is_meme():
    # Texture no longer guards this: the bright band alone is enough.
    frame = np.full((144, 256, 3), 40, dtype=np.uint8)
    frame[20:124, 64:192] = 230
    frame[100:106, :] = 255

    assert HeuristicClassifier().is_meme_frame(frame)


@pytest.mark.parametrize("value", [0, 255])
def test_plain_frame_is_not_meme(value):
    assert not HeuristicClassifier().is_meme_frame(np.full((144, 256, 3), value, dtype=np.uint8))


def test_larger_frame_is_resized_before_scoring():
    card = glitch_card()
    upscaled = cv2.resize(card, (512, 288), interpolation=cv2.INTER_NEAREST)

    assert HeuristicClassifier.scores(upscaled) == HeuristicClassifier.scores(card)


def test_threshold_is_configurable():
    classifier = HeuristicClassifier(band_threshold=1000.0)

    assert classifier.band_threshold == 1000.0
    assert not classifier.is_meme_frame(glitch_card())


def test_is_meme_frame_writes_no_file():
    with (
        mock.patch("tempfile.TemporaryDirectory", side_effect=AssertionError("temporary directory created")),
        mock.patch("cv2.imwrite", side_effect=AssertionError("image written")),
    ):
        assert HeuristicClassifier().is_meme_frame(glitch_card())


def test_is_meme_reads_the_file_without_a_subprocess(tmp_path):
    path = tmp_path / "card.png"
    cv2.imwrite(str(path), glitch_card())

    with mock.patch("subprocess.run", side_effect=AssertionError("subprocess started")):
        assert HeuristicClassifier().is_meme(path)


def test_unreadable_image_raises(tmp_path):
    not_an_image = tmp_path / "not_an_image.png"
    not_an_image.write_text("hello")

    for path in [tmp_path / "missing.png", not_an_image]:
        with pytest.raises(RuntimeError, match=str(path)):
            HeuristicClassifier().is_meme(path)


def test_labeled_positives(labeled_positive_paths):
    assert labeled_positive_paths
    classifier = HeuristicClassifier()
    assert [path.name for path in labeled_positive_paths if not classifier.is_meme(path)] == []


def test_labeled_negatives(labeled_negative_paths):
    assert labeled_negative_paths
    classifier = HeuristicClassifier()
    assert [path.name for path in labeled_negative_paths if classifier.is_meme(path)] == []


def test_extra_positive():
    if not EXTRA_POSITIVE.is_file():
        pytest.skip(f"fixture {EXTRA_POSITIVE} is absent")
    assert HeuristicClassifier().is_meme(EXTRA_POSITIVE)
