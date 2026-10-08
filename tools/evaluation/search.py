"""Search for the smallest combination of criteria that classifies the labeled frames.

A rule is a union of terms (`AnyOf`), each a conjunction (`AllOf`) of threshold conditions
(`Condition`), found by beam search over candidate conditions and then refined: every threshold is
moved to the middle of the widest score gap that leaves the rule's weighted cost unchanged, so it sits
away from the edge of the data.
"""

from dataclasses import dataclass

import numpy as np

from extract_memes.rule_classifier import AllOf, AnyOf, Condition, Rule

from .data import Samples
from .metrics import DEFAULT_FN_WEIGHT, best_threshold
from .truth import POSITIVE

QUANTILES = 40  # candidate thresholds per criterion, direction and class source
BEAM_WIDTH = 12


@dataclass(frozen=True)
class Score:
    fn: int
    fp: int
    cost: float


@dataclass(frozen=True)
class Found:
    rule: Rule
    score: Score
    terms: int
    conditions: int
    gaps: dict  # (criterion, op) -> (gap width, gap width / criterion spread)


def rule_mask(rule: Rule, scores: dict[str, np.ndarray]) -> np.ndarray:
    """Whether `rule` holds for each frame, from per-criterion score arrays."""
    if isinstance(rule, Condition):
        values, bound = scores[rule.criterion], rule.value
        return {">": values > bound, ">=": values >= bound, "<": values < bound, "<=": values <= bound}[rule.op]
    parts = [rule_mask(part, scores) for part in rule.rules]
    return np.logical_and.reduce(parts) if isinstance(rule, AllOf) else np.logical_or.reduce(parts)


def score_mask(mask: np.ndarray, positive: np.ndarray, fn_weight: float) -> Score:
    fn = int((positive & ~mask).sum())
    fp = int((~positive & mask).sum())
    return Score(fn, fp, fn_weight * fn + fp)


def evaluate_rule(rule: Rule, samples: Samples, fn_weight: float = DEFAULT_FN_WEIGHT) -> tuple[Score, np.ndarray]:
    """The rule's errors on the labeled frames of `samples`, and its decision for every frame."""
    mask = rule_mask(rule, samples.scores)
    labeled = samples.labels >= 0
    return score_mask(mask[labeled], samples.labels[labeled] == POSITIVE, fn_weight), mask


@dataclass
class _Candidates:
    names: list[str]
    directions: np.ndarray  # +1: score > cut, -1: score < cut
    cuts: np.ndarray  # in the criterion's own units
    matrix: np.ndarray  # bool, one row per candidate, one column per frame

    def label(self, i: int) -> tuple[str, int]:
        return self.names[i], int(self.directions[i])


def _candidates(scores: dict[str, np.ndarray], positive: np.ndarray) -> _Candidates:
    names, directions, cuts, rows = [], [], [], []
    for name, values in scores.items():
        distinct = np.unique(values)
        if len(distinct) < 2:
            continue
        picks = np.unique(np.concatenate([
            np.quantile(values[positive], np.linspace(0, 1, QUANTILES), method="nearest"),
            np.quantile(values[~positive], np.linspace(0, 1, QUANTILES), method="nearest"),
            np.quantile(values, np.linspace(0, 1, QUANTILES), method="nearest"),
        ]))
        above = np.searchsorted(distinct, picks, side="right")  # index of the next distinct value
        picks = picks[above < len(distinct)]
        above = above[above < len(distinct)]
        for cut in (picks + distinct[above]) / 2:
            for direction in (1, -1):
                names.append(name)
                directions.append(direction)
                cuts.append(cut)
                rows.append(values > cut if direction > 0 else values < cut)
    return _Candidates(names, np.array(directions), np.array(cuts), np.array(rows))


def _beam_term(cand: _Candidates, positive: np.ndarray, base: np.ndarray, max_conditions: int,
               fn_weight: float, beam: int = BEAM_WIDTH) -> tuple[tuple[int, ...], np.ndarray] | None:
    """The conjunction (candidate indexes) that most lowers the cost of `base | term`, or None."""
    n_pos = int(positive.sum())
    matrix = cand.matrix
    states = [((), np.ones(matrix.shape[1], dtype=bool))]
    best, best_cost = None, np.inf
    for _ in range(max_conditions):
        scored = []
        for chosen, term in states:
            union = matrix & term | base
            tp = (union & positive).sum(axis=1)
            fp = (union & ~positive).sum(axis=1)
            cost = fn_weight * (n_pos - tp) + fp
            used = {(cand.names[i], int(cand.directions[i])) for i in chosen}
            for i in np.argsort(cost, kind="stable")[: beam + len(chosen) + 2]:
                if cand.label(i) not in used:
                    scored.append((float(cost[i]), chosen + (int(i),), i, term))
        scored.sort(key=lambda s: s[0])
        states, seen = [], set()
        for cost, chosen, i, term in scored:
            key = frozenset(chosen)
            if key in seen:
                continue
            seen.add(key)
            states.append((chosen, term & matrix[i]))
            if cost < best_cost:
                best, best_cost = (chosen, term & matrix[i]), cost
            if len(states) == beam:
                break
    return best


def _condition(name: str, direction: int, cut: float) -> Condition:
    return Condition(name, ">" if direction > 0 else "<", cut)


def _refine(terms: list[list[tuple[str, int, float]]], samples: Samples, positive: np.ndarray,
            fn_weight: float, passes: int = 2) -> tuple[list[list[tuple[str, int, float]]], dict]:
    """Move each threshold to the middle of the widest gap that doesn't raise the rule's cost."""
    scores = samples.scores
    gaps: dict = {}
    for _ in range(passes):
        for ti, term in enumerate(terms):
            for ci, (name, direction, cut) in enumerate(term):
                others = np.ones(len(positive), dtype=bool)
                for cj, (n2, d2, c2) in enumerate(term):
                    if cj != ci:
                        others &= scores[n2] > c2 if d2 > 0 else scores[n2] < c2
                elsewhere = np.zeros(len(positive), dtype=bool)
                for tj, other in enumerate(terms):
                    if tj != ti:
                        elsewhere |= np.logical_and.reduce(
                            [scores[n2] > c2 if d2 > 0 else scores[n2] < c2 for n2, d2, c2 in other])
                decided = others & ~elsewhere
                if not decided.any() or positive[decided].all() or not positive[decided].any():
                    gaps[(name, ">" if direction > 0 else "<")] = (float("nan"), float("nan"))
                    continue
                oriented = scores[name][decided] * direction
                found = best_threshold(oriented, positive[decided], fn_weight)
                own_cut = found.value * direction
                spread = np.subtract(*np.percentile(scores[name], [75, 25])) or 1.0
                terms[ti][ci] = (name, direction, own_cut)
                gaps[(name, ">" if direction > 0 else "<")] = (found.gap, found.gap / spread)
    return terms, gaps


def _round_into_gap(value: float) -> float:
    rounded = float(f"{value:.4g}")
    return rounded if abs(rounded - value) <= abs(value) * 2e-3 else value


def _build(terms) -> Rule:
    built = []
    for term in terms:
        conds = [_condition(n, d, _round_into_gap(c)) for n, d, c in term]
        built.append(conds[0] if len(conds) == 1 else AllOf(*conds))
    return built[0] if len(built) == 1 else AnyOf(*built)


def search(samples: Samples, max_conditions: int = 3, max_terms: int = 3,
           fn_weight: float = DEFAULT_FN_WEIGHT) -> list[Found]:
    """The best rule for each cap of 1..`max_conditions` conditions per term (up to `max_terms` terms).

    Frames the dataset leaves ignored are not used. Rules come back refined, cheapest cap first.
    """
    labeled = samples.labeled()
    positive = labeled.labels == POSITIVE
    cand = _candidates(labeled.scores, positive)
    results = []
    for cap in range(1, max_conditions + 1):
        base = np.zeros(len(positive), dtype=bool)
        chosen_terms: list[list[tuple[str, int, float]]] = []
        cost = fn_weight * positive.sum() + 0.0  # an empty rule misses every meme
        for _ in range(max_terms):
            found = _beam_term(cand, positive, base, cap, fn_weight)
            if found is None:
                break
            indexes, term_mask = found
            new_cost = score_mask(base | term_mask, positive, fn_weight).cost
            if new_cost >= cost:
                break
            cost, base = new_cost, base | term_mask
            chosen_terms.append([(cand.names[i], int(cand.directions[i]), float(cand.cuts[i])) for i in indexes])
        if not chosen_terms:
            continue
        refined, gaps = _refine(chosen_terms, labeled, positive, fn_weight)
        rule = _build(refined)
        score, _ = evaluate_rule(rule, labeled, fn_weight)
        if all(repr(rule) != repr(earlier.rule) for earlier in results):
            results.append(Found(rule, score, len(refined), sum(len(t) for t in refined), gaps))
    return results
