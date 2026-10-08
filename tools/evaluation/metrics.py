"""How well one criterion separates memes from non-memes.

All measures are taken in the criterion's *oriented* score: the score itself when memes score higher,
its negation when they score lower, so "higher means meme" everywhere below.
"""

from dataclasses import dataclass

import numpy as np

DEFAULT_FN_WEIGHT = 10.0  # a missed meme is a silent error; a false positive is caught on review


@dataclass(frozen=True)
class Threshold:
    """A cut on oriented scores: frames scoring above `value` are called memes."""

    value: float
    low: float  # the largest oriented score at or below the cut (the gap's lower end)
    high: float  # the smallest oriented score above the cut (the gap's upper end)
    fn: int
    fp: int
    cost: float

    @property
    def gap(self) -> float:
        """Width of the score interval over which the cut gives the same errors."""
        return self.high - self.low


@dataclass(frozen=True)
class CriterionReport:
    name: str
    direction: int  # +1: memes score higher (rule `>`), -1: lower (rule `<`)
    positives: int
    negatives: int
    threshold: float  # in the criterion's own units
    op: str
    fn: int
    fp: int
    precision: float
    recall: float
    safe_low: float  # own units; the cut can be anywhere in (safe_low, safe_high) with the same errors
    safe_high: float
    margin: float  # min(positive) - max(negative), oriented: > 0 separable, < 0 overlap
    robust_margin: float  # same with the 1st / 99th percentiles
    normalized_margin: float  # margin / interquartile range of all scores
    auc: float
    dprime: float
    cost: float


def orientation(values: np.ndarray, positive: np.ndarray) -> int:
    """+1 when positives tend to score higher than negatives, else -1."""
    return 1 if auc(values, positive) >= 0.5 else -1


def auc(values: np.ndarray, positive: np.ndarray) -> float:
    """P(random positive scores above random negative), ties counting half (Mann-Whitney U)."""
    n_pos, n_neg = int(positive.sum()), int((~positive).sum())
    if not n_pos or not n_neg:
        return float("nan")
    _, inverse, counts = np.unique(values, return_inverse=True, return_counts=True)
    ranks = (np.cumsum(counts) - (counts - 1) / 2.0)[inverse]  # average 1-based rank of each tie group
    return float((ranks[positive].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def best_threshold(oriented: np.ndarray, positive: np.ndarray, fn_weight: float = DEFAULT_FN_WEIGHT) -> Threshold:
    """The cut with the lowest `fn_weight * FN + FP`; ties go to the widest gap, then the lowest cut.

    Every cut between two consecutive distinct scores gives the same decisions, so it is placed at the
    middle of that gap (cuts below the minimum / above the maximum are included, with half-unit gaps
    stood in by the spread of the scores).
    """
    order = np.argsort(oriented, kind="stable")
    values, pos = oriented[order], positive[order]
    distinct, start = np.unique(values, return_index=True)
    pos_cum = np.concatenate([[0], np.cumsum(pos)])
    neg_cum = np.concatenate([[0], np.cumsum(~pos)])
    # cut k puts the first start[k] sorted frames at or below it (called non-memes)
    bounds = np.concatenate([[0], start[1:], [len(values)]])  # cut after distinct[k-1], k = 0..len(distinct)
    below_pos, below_neg = pos_cum[bounds], neg_cum[bounds]
    fn = below_pos
    fp = neg_cum[-1] - below_neg
    cost = fn_weight * fn + fp
    span = float(distinct[-1] - distinct[0]) or 1.0
    lows = np.concatenate([[distinct[0] - span], distinct])
    highs = np.concatenate([distinct, [distinct[-1] + span]])
    gaps = highs - lows
    # sort key: cost, then wider gap first (negated), then lower position
    pick = int(np.lexsort((np.arange(len(cost)), -gaps, cost))[0])
    return Threshold(float((lows[pick] + highs[pick]) / 2), float(lows[pick]), float(highs[pick]),
                     int(fn[pick]), int(fp[pick]), float(cost[pick]))


def evaluate_criterion(
    name: str, values: np.ndarray, positive: np.ndarray, fn_weight: float = DEFAULT_FN_WEIGHT
) -> CriterionReport:
    """Every measure of one criterion over labeled frames (`positive` is a boolean per frame)."""
    direction = orientation(values, positive)
    oriented = values * direction
    cut = best_threshold(oriented, positive, fn_weight)
    pos, neg = oriented[positive], oriented[~positive]
    quartiles = np.percentile(oriented, [25, 75])
    spread = float(quartiles[1] - quartiles[0]) or float(oriented.std()) or 1.0
    margin = float(pos.min() - neg.max())
    robust = float(np.percentile(pos, 1) - np.percentile(neg, 99))
    pooled = np.sqrt((pos.var() + neg.var()) / 2) or 1.0
    called = len(pos) - cut.fn + cut.fp
    own = lambda x: float(x * direction)  # noqa: E731 - back to the criterion's units
    safe = sorted((own(cut.low), own(cut.high)))
    return CriterionReport(
        name=name, direction=direction, positives=len(pos), negatives=len(neg),
        threshold=own(cut.value), op=">" if direction > 0 else "<", fn=cut.fn, fp=cut.fp,
        precision=(len(pos) - cut.fn) / called if called else float("nan"),
        recall=(len(pos) - cut.fn) / len(pos),
        safe_low=safe[0], safe_high=safe[1],
        margin=margin, robust_margin=robust, normalized_margin=margin / spread,
        auc=auc(oriented, positive), dprime=float((pos.mean() - neg.mean()) / pooled), cost=cut.cost,
    )
