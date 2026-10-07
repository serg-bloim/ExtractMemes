"""Classifier criteria: numeric scores of a frame, one module per criterion.

A criterion is a function from a BGR frame to a number. Each lives in its own module in this package
and registers itself with `@criterion("name")`; `all_criteria()` imports every module here, so adding
a criterion is adding one file, and anything that lists criteria (the labeler, `RuleClassifier`)
sees it without further wiring.

Rules for a criterion module, which keep its cache fingerprint honest:
- it defines one criterion (plus private helpers) and imports shared code only from `._common`;
- it scores a frame of any size by first bringing it to the scan size (`_common.scan_size`), so the
  score doesn't depend on which resolution the video was downloaded at.

Importing this package registers nothing and does no work; the modules are imported by
`all_criteria()` / `get()`.
"""

import hashlib
import importlib
import pkgutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class Criterion:
    """A named score of a frame. `module` is the module that defines it (None for an ad-hoc one)."""

    name: str
    score: Callable[[np.ndarray], float]
    description: str = ""
    module: str | None = None

    def fingerprint(self) -> str:
        """Changes when this criterion's code changes, which invalidates anything cached from it.

        It hashes the criterion's module and the shared `_common` module; an ad-hoc criterion with
        no module hashes its function's source instead.
        """
        digest = hashlib.sha1()
        if self.module is None:
            import inspect

            digest.update(inspect.getsource(self.score).encode())
        else:
            for name in (self.module, f"{__name__}._common"):
                digest.update(Path(sys.modules[name].__file__).read_bytes())
        return digest.hexdigest()[:12]


_REGISTRY: dict[str, Criterion] = {}


def criterion(name: str) -> Callable[[Callable[[np.ndarray], float]], Callable[[np.ndarray], float]]:
    """Register the decorated function as the criterion `name`; its docstring is the description."""

    def register(function):
        if name in _REGISTRY and _REGISTRY[name].score is not function:
            raise ValueError(f"A criterion named {name!r} is already registered")
        _REGISTRY[name] = Criterion(
            name=name,
            score=function,
            description=" ".join((function.__doc__ or "").split()),
            module=function.__module__,
        )
        return function

    return register


def _import_all() -> None:
    for module in pkgutil.iter_modules(__path__):
        if not module.name.startswith("_"):
            importlib.import_module(f"{__name__}.{module.name}")


def all_criteria() -> dict[str, Criterion]:
    """Every criterion in this package, by name, in name order."""
    _import_all()
    return {name: _REGISTRY[name] for name in sorted(_REGISTRY)}


def get(name: str) -> Criterion:
    """The criterion called `name`; raises `KeyError` listing the known names."""
    criteria = all_criteria()
    if name not in criteria:
        raise KeyError(f"No criterion named {name!r}; known: {', '.join(criteria)}")
    return criteria[name]
