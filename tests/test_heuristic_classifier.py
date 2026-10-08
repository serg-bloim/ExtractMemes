from pathlib import Path
from unittest import mock

import cv2
import numpy as np
import pytest

from extract_memes.heuristic_classifier import HeuristicClassifier

EXTRA_POSITIVE = Path(__file__).resolve().parent.parent / "sample" / "quick_frame_9-32.png"


@pytest.fixture
def card_path(labeled_positive_paths) -> Path:
    return labeled_positive_paths[0]


@pytest.fixture
def card(card_path) -> np.ndarray:
    return cv2.imread(str(card_path))


def test_a_labeled_card_is_meme(card):
    assert HeuristicClassifier().is_meme_frame(card)


def test_a_labeled_non_card_is_not_meme(labeled_negative_paths):
    assert not HeuristicClassifier().is_meme_frame(cv2.imread(str(labeled_negative_paths[0])))


@pytest.mark.parametrize("value", [0, 128, 255])
def test_plain_frame_is_not_meme(value):
    assert not HeuristicClassifier().is_meme_frame(np.full((144, 256, 3), value, dtype=np.uint8))


def test_the_rule_is_edge_histogram_below_the_threshold(card):
    score = HeuristicClassifier.scores(card).edge_histogram

    assert HeuristicClassifier(edge_histogram_threshold=score + 0.01).is_meme_frame(card)
    assert not HeuristicClassifier(edge_histogram_threshold=score).is_meme_frame(card)  # strict


def test_larger_frame_is_resized_before_scoring(card):
    upscaled = cv2.resize(card, (512, 288), interpolation=cv2.INTER_NEAREST)

    assert HeuristicClassifier.scores(upscaled) == HeuristicClassifier.scores(card)


def test_threshold_is_configurable(card):
    classifier = HeuristicClassifier(edge_histogram_threshold=0.0)

    assert classifier.edge_histogram_threshold == 0.0
    assert not classifier.is_meme_frame(card)


def test_is_meme_frame_writes_no_file(card):
    with (
        mock.patch("tempfile.TemporaryDirectory", side_effect=AssertionError("temporary directory created")),
        mock.patch("cv2.imwrite", side_effect=AssertionError("image written")),
    ):
        assert HeuristicClassifier().is_meme_frame(card)


def test_is_meme_reads_the_file_without_a_subprocess(card_path):
    with mock.patch("subprocess.run", side_effect=AssertionError("subprocess started")):
        assert HeuristicClassifier().is_meme(card_path)


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
