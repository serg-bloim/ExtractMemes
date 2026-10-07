from unittest import mock

import cv2
import numpy as np
import pytest

from extract_memes import criteria
from extract_memes.criteria import Criterion
from extract_memes.rule_classifier import AllOf, AnyOf, Condition, RuleClassifier


def glitch_card() -> np.ndarray:
    """Dark multicolored noise, a light central card, and a white full-width band."""
    frame = np.random.default_rng(0).integers(0, 120, (144, 256, 3), dtype=np.uint8)
    frame[20:124, 64:192] = 230
    frame[100:106, :] = 255
    return frame


@pytest.mark.parametrize(
    "op, value, expected",
    [(">", 5.0, False), (">", 4.0, True), (">=", 5.0, True), ("<", 5.0, False), ("<", 6.0, True), ("<=", 5.0, True)],
)
def test_condition_compares_a_criterions_score_with_a_value(op, value, expected):
    assert Condition("c", op, value).evaluate({"c": 5.0}) == expected


def test_condition_rejects_an_unknown_operator():
    with pytest.raises(ValueError, match="op must be one of"):
        Condition("c", "==", 1)


def test_all_of_and_any_of_combine_conditions():
    low, high = Condition("a", "<", 1), Condition("b", ">", 10)
    scores = {"a": 0.5, "b": 3.0}

    assert not AllOf(low, high).evaluate(scores)
    assert AnyOf(low, high).evaluate(scores)
    assert AllOf(low, AnyOf(high, Condition("b", "<", 5))).evaluate(scores)
    with pytest.raises(ValueError, match="at least one"):
        AllOf()


def test_a_rule_knows_its_conditions_and_the_criteria_it_needs_once_each():
    rule = AllOf(Condition("band", ">", 180), AnyOf(Condition("margin_luma", "<", 35), Condition("band", "<", 300)))

    assert [(c.criterion, c.op, c.value) for c in rule.conditions()] == [
        ("band", ">", 180.0), ("margin_luma", "<", 35.0), ("band", "<", 300.0)]
    assert rule.criterion_names() == ["band", "margin_luma"]


def test_a_rule_classifier_combines_criteria_into_a_verdict():
    card = glitch_card()  # band ~ 195, margins are dark noise with a mean of about 60

    assert RuleClassifier(Condition("band", ">", 180)).is_meme_frame(card)
    assert RuleClassifier(AllOf(Condition("band", ">", 180), Condition("margin_luma", "<", 100))).is_meme_frame(card)
    assert not RuleClassifier(AllOf(Condition("band", ">", 180), Condition("margin_luma", "<", 30))).is_meme_frame(card)
    assert RuleClassifier(AnyOf(Condition("band", ">", 1000), Condition("margin_luma", "<", 100))).is_meme_frame(card)


def test_an_unknown_criterion_fails_when_the_classifier_is_built():
    with pytest.raises(KeyError, match="No criterion named 'nope'"):
        RuleClassifier(Condition("nope", ">", 1))


def test_only_the_criteria_a_rule_uses_are_computed(monkeypatch):
    def boom(frame):
        raise AssertionError("texture must not be computed")

    criteria.all_criteria()
    monkeypatch.setattr(criteria, "_REGISTRY", {**criteria._REGISTRY, "texture": Criterion("texture", boom)})

    classifier = RuleClassifier(Condition("band", ">", 180))

    assert classifier.is_meme_frame(glitch_card())
    assert set(classifier.criterion_scores(glitch_card())) == {"band"}


def test_is_meme_reads_an_image_file(tmp_path):
    path = tmp_path / "card.png"
    cv2.imwrite(str(path), glitch_card())
    classifier = RuleClassifier(Condition("band", ">", 180))

    assert classifier.is_meme(path)
    with pytest.raises(RuntimeError, match="Could not read image"):
        classifier.is_meme(tmp_path / "missing.png")


def test_the_fingerprint_changes_with_the_rule_and_with_a_criterions_code(monkeypatch):
    base = RuleClassifier(Condition("band", ">", 180)).fingerprint()

    assert RuleClassifier(Condition("band", ">", 180)).fingerprint() == base
    assert RuleClassifier(Condition("band", ">", 170)).fingerprint() != base

    with mock.patch.object(criteria.get("band").__class__, "fingerprint", lambda self: "changed"):
        assert RuleClassifier(Condition("band", ">", 180)).fingerprint() != base
