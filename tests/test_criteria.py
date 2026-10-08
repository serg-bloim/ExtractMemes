import sys
import textwrap

import numpy as np
import pytest

from extract_memes import criteria
from extract_memes.criteria import Criterion, criterion
from extract_memes.heuristic_classifier import HeuristicClassifier


def glitch_card() -> np.ndarray:
    """Dark multicolored noise, a light central card, and a white full-width band."""
    frame = np.random.default_rng(0).integers(0, 120, (144, 256, 3), dtype=np.uint8)
    frame[20:124, 64:192] = 230
    frame[100:106, :] = 255
    return frame


@pytest.fixture
def scratch_registry(monkeypatch):
    """A copy of the registry that the test can add to without leaking into other tests."""
    monkeypatch.setattr(criteria, "_REGISTRY", dict(criteria._REGISTRY))


def test_the_package_lists_its_criteria_by_name():
    found = criteria.all_criteria()

    assert list(found) == ["band", "edge_black", "edge_histogram", "hue_consistency", "margin_luma", "texture"]
    assert all(c.name == name and c.description and c.module for name, c in found.items())


def test_get_names_the_known_criteria_when_one_is_missing():
    assert criteria.get("band").name == "band"
    with pytest.raises(KeyError, match="known: band, edge_black, edge_histogram, hue_consistency"):
        criteria.get("nope")


def test_registering_a_second_criterion_under_a_taken_name_fails(scratch_registry):
    criteria.all_criteria()

    with pytest.raises(ValueError, match="already registered"):

        @criterion("band")
        def other(frame):
            return 0.0


def test_a_registered_criterion_shows_up_in_the_listing(scratch_registry):
    @criterion("brightness")
    def brightness(frame):
        """Mean brightness."""
        return float(frame.mean())

    found = criteria.all_criteria()

    assert "brightness" in found and found["brightness"].description == "Mean brightness."
    assert found["brightness"].score is brightness


def test_a_new_module_in_the_package_is_found_without_any_wiring(scratch_registry, monkeypatch, tmp_path):
    (tmp_path / "dropped_in.py").write_text(textwrap.dedent('''
        from extract_memes.criteria import criterion


        @criterion("dropped_in")
        def dropped_in(frame):
            """A criterion added as a file."""
            return 42.0
    '''))
    monkeypatch.setattr(criteria, "__path__", [*criteria.__path__, str(tmp_path)])
    try:
        found = criteria.all_criteria()
    finally:
        sys.modules.pop("extract_memes.criteria.dropped_in", None)

    assert "dropped_in" in found
    assert found["dropped_in"].score(glitch_card()) == 42.0


def test_the_fingerprint_changes_with_the_criterions_code(scratch_registry, monkeypatch, tmp_path):
    module = tmp_path / "fp_demo.py"
    module.write_text("from extract_memes.criteria import criterion\n\n@criterion('fp_demo')\ndef f(frame):\n    return 1.0\n")
    monkeypatch.setattr(criteria, "__path__", [*criteria.__path__, str(tmp_path)])
    try:
        found = criteria.all_criteria()["fp_demo"]
        before = found.fingerprint()
        assert found.fingerprint() == before
        module.write_text(module.read_text().replace("1.0", "2.0"))
        assert found.fingerprint() != before
    finally:
        sys.modules.pop("extract_memes.criteria.fp_demo", None)


def test_an_ad_hoc_criterion_is_fingerprinted_by_its_function_source():
    def one(frame):
        return 1.0

    def two(frame):
        return 2.0

    assert Criterion("x", one).fingerprint() == Criterion("y", one).fingerprint()
    assert Criterion("x", one).fingerprint() != Criterion("x", two).fingerprint()


@pytest.mark.parametrize("name", ["band", "texture", "margin_luma", "hue_consistency", "edge_black", "edge_histogram"])
def test_a_score_does_not_depend_on_the_frames_resolution(name):
    card = glitch_card()
    upscaled = np.repeat(np.repeat(card, 2, axis=0), 2, axis=1)

    assert criteria.get(name).score(upscaled) == pytest.approx(criteria.get(name).score(card), rel=0.05)


def test_the_heuristic_classifiers_scores_are_the_criteria_scores():
    card = glitch_card()

    scores = HeuristicClassifier.scores(card)

    assert scores.band == criteria.get("band").score(card)
    assert scores.texture == criteria.get("texture").score(card)
    assert scores.edge_histogram == criteria.get("edge_histogram").score(card)


def test_margin_luma_tells_dark_static_from_a_bright_scene():
    static = np.random.default_rng(1).integers(0, 40, (144, 256, 3), dtype=np.uint8)
    scene = np.full((144, 256, 3), 200, dtype=np.uint8)

    assert criteria.get("margin_luma").score(static) < 30 < criteria.get("margin_luma").score(scene)


def test_hue_consistency_tells_one_hue_from_mixed_colours():
    one_hue = np.zeros((144, 256, 3), dtype=np.uint8)
    one_hue[...] = (180, 40, 120)  # a single purple
    mixed = np.random.default_rng(2).integers(0, 255, (144, 256, 3), dtype=np.uint8)

    assert criteria.get("hue_consistency").score(one_hue) > 0.95
    assert criteria.get("hue_consistency").score(mixed) < 0.3


def test_edge_black_is_the_percentage_of_near_black_pixels_in_the_outer_edges():
    score = criteria.get("edge_black").score
    frame = np.full((144, 256, 3), 200, dtype=np.uint8)

    assert score(frame) == 0
    frame[:, :13] = 0  # the whole left edge, half of the 26 edge columns
    assert score(frame) == pytest.approx(50)
    frame[:, -13:] = 0
    assert score(frame) == 100
    frame[:, :13] = 12  # brightness 12 is under 5% of 255 (12.75), 13 is not
    frame[:, -13:] = 13
    assert score(frame) == pytest.approx(50)


def test_edge_black_ignores_everything_inside_the_edges():
    frame = np.full((144, 256, 3), 255, dtype=np.uint8)
    frame[:, 13:-13] = 0

    assert criteria.get("edge_black").score(frame) == 0
