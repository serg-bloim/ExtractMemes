"""Text, CSV and JSON output of the evaluation."""

import csv
import dataclasses
import json
from pathlib import Path

import numpy as np

from .data import Samples
from .metrics import CriterionReport
from .search import Found, missed_memes
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
        memes = len(set(samples.window[mine & (samples.labels == POSITIVE)]))
        parts.append(f"{video}: {memes} memes ({int((labels == POSITIVE).sum())} positive frames), "
                     f"{int((labels == 0).sum())} negative, {int((labels == IGNORED).sum())} ignored")
    return "Frames used -- " + "; ".join(parts)


def criteria_table(reports: list[CriterionReport], rank: str = "cost") -> str:
    reports = sorted(reports, key=RANK_KEYS[rank])
    head = (f"{'criterion':<18}{'rule':<16}{'FN':>5}{'FP':>6}{'FP rate':>9}{'recall':>8}{'margin':>10}"
            f"{'robust':>10}{'norm':>8}{'AUC':>7}{'d′':>7}  safe interval")
    lines = [head, "-" * len(head)]
    for r in reports:
        lines.append(
            f"{r.name:<18}{f'{r.op} {r.threshold:.4g}':<16}{r.fn:>5}{r.fp:>6}{r.fp_rate:>9.4f}{r.recall:>8.3f}"
            f"{r.margin:>10.4g}{r.robust_margin:>10.4g}{r.normalized_margin:>8.2f}{r.auc:>7.3f}{r.dprime:>7.2f}"
            f"  ({r.safe_low:.4g}, {r.safe_high:.4g})")
    return "\n".join(lines)


def separation_table(reports: list[CriterionReport], samples: Samples) -> str:
    """Where each criterion's margin comes from: its weakest meme and its strongest non-meme."""
    lines = ["Separation (oriented so higher = more meme-like; a meme is represented by its best frame)",
             f"{'criterion':<18}{'weakest meme':>14}{'strongest non-meme':>20}{'gap':>10}  weakest meme at / strongest non-meme at"]
    lines.append("-" * 110)
    for r in sorted(reports, key=lambda r: -r.normalized_margin):
        lo, hi = samples.scores[r.name][r.weakest] * r.direction, samples.scores[r.name][r.strongest] * r.direction
        where = lambda i: f"{samples.video[i]} {samples.ts[i]:.2f}s"  # noqa: E731
        lines.append(f"{r.name:<18}{lo:>14.4g}{hi:>20.4g}{r.margin:>10.4g}  {where(r.weakest)} / {where(r.strongest)}")
    return "\n".join(lines)


PERCENTILES = (1, 5, 25, 50, 75, 95, 99)


def window_extremes(values: np.ndarray, samples: Samples) -> tuple[np.ndarray, np.ndarray]:
    """Each meme's highest and lowest score over its frames (one number each per meme)."""
    positive = np.flatnonzero(samples.labels == POSITIVE)
    _, inverse = np.unique(samples.window[positive], return_inverse=True)
    high = np.full(inverse.max() + 1, -np.inf)
    low = np.full(inverse.max() + 1, np.inf)
    np.maximum.at(high, inverse, values[positive])
    np.minimum.at(low, inverse, values[positive])
    return high, low


def distributions(samples: Samples, bins: int = 16, width: int = 12) -> str:
    """Per criterion: the spread of the memes' highs, the memes' lows and the non-meme frames' scores."""
    labeled = samples.labeled()
    non_meme = labeled.labels != POSITIVE
    out = []
    for name, values in labeled.scores.items():
        high, low = window_extremes(values, labeled)
        series = [("meme highs", high), ("meme lows", low), ("non-meme frames", values[non_meme])]
        out += [f"{name}  ({len(high)} memes, {int(non_meme.sum())} non-meme frames)",
                f"  {'':<16}{'min':>9}" + "".join(f"{f'p{q}':>9}" for q in PERCENTILES) + f"{'max':>9}"]
        for label, data in series:
            cells = [data.min(), *np.percentile(data, PERCENTILES), data.max()]
            out.append(f"  {label:<16}" + "".join(f"{c:>9.4g}" for c in cells))
        edges = np.linspace(min(d.min() for _, d in series), max(d.max() for _, d in series), bins + 1)
        shares = [np.histogram(d, edges)[0] / len(d) for _, d in series]
        peak = max(share.max() for share in shares) or 1.0
        out.append("  " + f"{'score range':<22}" + "".join(f"{label:<{width + 8}}" for label, _ in series))
        for k in range(bins):
            cells = "".join(
                f"{share[k] * 100:>5.1f}% {'#' * round(share[k] / peak * width):<{width + 1}}" for share in shares)
            out.append(f"  [{edges[k]:>8.4g}, {edges[k + 1]:>8.4g}) {cells}")
        out.append("")
    return "\n".join(out)


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
    """The misclassified labeled frames for a decision `mask`: memes detected nowhere, then false positives."""
    labeled = samples.labels != IGNORED
    positive = samples.labels == POSITIVE
    missed = missed_memes(samples, mask)
    false_positive = np.flatnonzero(labeled & ~positive & mask)
    lines = []
    for title, indexes in (("missed memes (FN)", missed), ("false positives (FP)", false_positive)):
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
