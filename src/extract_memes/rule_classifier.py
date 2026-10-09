"""Classify frames with a rule over criterion scores: conditions combined with all-of / any-of."""

import hashlib
import operator
from abc import ABC, abstractmethod
from collections.abc import Mapping
from pathlib import Path

import cv2
import numpy as np

from extract_memes import criteria
from extract_memes.classifier import FrameClassifier

_OPERATORS = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le}


class Rule(ABC):
    """A yes/no decision from a frame's criterion scores."""

    @abstractmethod
    def evaluate(self, scores: Mapping[str, float]) -> bool:
        """Whether the rule holds for `scores` (criterion name -> score)."""

    @abstractmethod
    def conditions(self) -> list["Condition"]:
        """Every condition in the rule, so a tool can show the thresholds it uses."""

    def criterion_names(self) -> list[str]:
        """The criteria the rule needs, each once, in the order they first appear."""
        return list(dict.fromkeys(condition.criterion for condition in self.conditions()))


class Condition(Rule):
    """`criterion op value`, e.g. `Condition("band", ">", 180)`; `op` is one of > >= < <=."""

    def __init__(self, criterion: str, op: str, value: float) -> None:
        if op not in _OPERATORS:
            raise ValueError(f"op must be one of {', '.join(_OPERATORS)}, not {op!r}")
        self.criterion, self.op, self.value = criterion, op, float(value)

    def evaluate(self, scores: Mapping[str, float]) -> bool:
        return _OPERATORS[self.op](scores[self.criterion], self.value)

    def conditions(self) -> list["Condition"]:
        return [self]

    def __repr__(self) -> str:
        return f"Condition({self.criterion!r}, {self.op!r}, {self.value!r})"

    def __str__(self) -> str:
        return f"{self.criterion} {self.op} {self.value:g}"


class _Combination(Rule):
    def __init__(self, *rules: Rule) -> None:
        if not rules:
            raise ValueError(f"{type(self).__name__} needs at least one rule")
        self.rules = rules

    def conditions(self) -> list[Condition]:
        return [condition for rule in self.rules for condition in rule.conditions()]

    def __repr__(self) -> str:
        return f"{type(self).__name__}({', '.join(map(repr, self.rules))})"

    def __str__(self) -> str:
        word = " and " if isinstance(self, AllOf) else " or "
        return "(" + word.join(map(str, self.rules)) + ")"


class AllOf(_Combination):
    """Holds when every part holds."""

    def evaluate(self, scores: Mapping[str, float]) -> bool:
        return all(rule.evaluate(scores) for rule in self.rules)


class AnyOf(_Combination):
    """Holds when at least one part holds."""

    def evaluate(self, scores: Mapping[str, float]) -> bool:
        return any(rule.evaluate(scores) for rule in self.rules)


class RuleClassifier(FrameClassifier):
    """Flags a frame when `rule` holds for its criterion scores.

    Only the criteria the rule uses are computed, once per frame. A criterion name the package
    doesn't have raises `KeyError` at construction, not on the first frame.
    """

    def __init__(self, rule: Rule) -> None:
        self.rule = rule
        self._criteria = [criteria.get(name) for name in rule.criterion_names()]

    def criterion_scores(self, frame: np.ndarray) -> dict[str, float]:
        """The score of each criterion the rule uses, for a BGR frame."""
        return {criterion.name: criterion.score(frame) for criterion in self._criteria}

    def is_meme_frame(self, frame: np.ndarray) -> bool:
        return self.rule.evaluate(self.criterion_scores(frame))

    def is_meme(self, image_path: Path) -> bool:
        frame = cv2.imread(str(image_path))
        if frame is None:
            raise RuntimeError(f"Could not read image: {image_path}")
        return self.is_meme_frame(frame)

    def fingerprint(self) -> str:
        """Changes when the rule or the code of any criterion it uses changes."""
        digest = hashlib.sha1(repr(self.rule).encode())
        for criterion in self._criteria:
            digest.update(criterion.fingerprint().encode())
        return digest.hexdigest()[:12]
