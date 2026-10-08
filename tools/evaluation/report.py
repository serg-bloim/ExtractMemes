"""Text, CSV and JSON output of the evaluation."""

import csv
import dataclasses
import json
from pathlib import Path

import numpy as np

from .data import Samples
from .metrics import CriterionReport
from .search import Found, Score
from .truth import IGNORED, POSITIVE

RANK_KEYS = {
    "cost": lambda r: (r.cost, -r.robust_margin),
    "margin": lambda r: -r.robust_margin,
    "auc": lambda r: -r.auc,
    "dprime": lambda r: -r.dprime,
}


def counts_line(samples: Samples) -> str:
    parts = []
    for video in dict.fromkeys(samples.video):
        mine = samples.video == video
        labels = samples.labels[mine]
        parts.append(f"{video}: {int((labels == POSITIVE).sum())} positive, "
                     f"{int((labels == 0).sum())} negative, {int((labels == IGNORED).sum())} ignored")
    return "Frames used -- " + "; ".join(parts)


def criteria_table(reports: list[CriterionReport], rank: str = "cost") -> str:
    reports = sorted(reports, key=RANK_KEYS[rank])
    head = (f"{'criterion':<18}{'rule':<16}{'FN':>5}{'FP':>6}{'prec':>7}{'recall':>8}{'margin':>10}"
            f"{'robust':>10}{'norm':>8}{'AUC':>7}{'d′':>7}  safe interval")
    lines = [head, "-" * len(head)]
    for r in reports:
        lines.append(
            f"{r.name:<18}{f'{r.op} {r.threshold:.4g}':<16}{r.fn:>5}{r.fp:>6}{r.precision:>7.3f}{r.recall:>8.3f}"
            f"{r.margin:>10.4g}{r.robust_margin:>10.4g}{r.normalized_margin:>8.2f}{r.auc:>7.3f}{r.dprime:>7.2f}"
            f"  ({r.safe_low:.4g}, {r.safe_high:.4g})")
    return "\n".join(lines)


def rules_table(found: list[Found], title: str = "Combinations") -> str:
    lines = [title, "-" * len(title)]
    for f in found:
        used = len({c.criterion for c in f.rule.conditions()})
        lines.append(f"{used} criteria, {f.conditions} condition(s) in {f.terms} term(s): FN {f.score.fn}, FP {f.score.fp}, cost {f.score.cost:g}")
        lines.append(f"    {f.rule!r}")
        widths = ", ".join(f"{name} {op}: gap {gap:.4g} ({norm:.2f} of spread)"
                           for (name, op), (gap, norm) in f.gaps.items())
        lines.append(f"    threshold gaps -- {widths}")
    return "\n".join(lines)


def errors_list(samples: Samples, mask: np.ndarray, limit: int) -> str:
    """The misclassified labeled frames for a decision `mask`, false negatives first."""
    labeled = samples.labels != IGNORED
    positive = samples.labels == POSITIVE
    lines = []
    for title, wrong in (("missed memes (FN)", positive & ~mask), ("false positives (FP)", labeled & ~positive & mask)):
        indexes = np.flatnonzero(wrong)
        lines.append(f"  {title}: {len(indexes)}")
        for i in indexes[:limit]:
            lines.append(f"    {samples.video[i]}  frame {samples.frame[i]}  {samples.ts[i]:.2f}s")
        if len(indexes) > limit:
            lines.append(f"    ... {len(indexes) - limit} more")
    return "\n".join(lines)


def write_csv(path: Path, reports: list[CriterionReport]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, [f.name for f in dataclasses.fields(CriterionReport)])
        writer.writeheader()
        writer.writerows(dataclasses.asdict(r) for r in reports)


def write_json(path: Path, reports: list[CriterionReport], found: list[Found]) -> None:
    payload = {
        "criteria": [dataclasses.asdict(r) for r in reports],
        "rules": [{"rule": repr(f.rule), "terms": f.terms, "conditions": f.conditions,
                   **dataclasses.asdict(f.score)} for f in found],
    }
    path.write_text(json.dumps(payload, indent=2, default=float))
