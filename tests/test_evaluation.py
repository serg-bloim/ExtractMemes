import numpy as np
import pytest

pytest.importorskip("yaml")

from extract_memes.rule_classifier import AllOf, AnyOf, Condition
from tools.evaluation.data import Samples, pool
from tools.evaluation.metrics import auc, best_threshold, evaluate_criterion
from tools.evaluation.search import evaluate_rule, missed_memes, rule_mask, search
from tools.evaluation.truth import IGNORED, NEGATIVE, POSITIVE, ground_truth
from tools.labeling.dataset import Dataset, Meme, NotMeme, VideoInfo

PTS = np.arange(400) / 25.0  # 25 fps
ROWS = np.arange(0, 400, 8)  # scan every 8th frame


def dataset(memes=(), not_memes=()) -> Dataset:
    video = VideoInfo("u", "vid", "160", "avc1", "mp4", 256, 144, 25.0, 400)
    return Dataset(video=video, memes=list(memes), not_memes=list(not_memes))


def label_of(labels, frame):
    return labels[list(ROWS).index(frame)]


def test_a_ranged_meme_makes_its_window_positive_and_the_rest_negative():
    meme = Meme(2.0, 50, start_ts=1.6, start_frame=40, end_ts=2.4, end_frame=60)
    labels, windows = ground_truth(dataset([meme]), ROWS, PTS)
    assert [label_of(labels, f) for f in (32, 40, 48, 56, 64)] == [NEGATIVE, POSITIVE, POSITIVE, POSITIVE, NEGATIVE]
    assert (labels == IGNORED).sum() == 0


def test_a_single_frame_mark_is_positive_with_an_ignore_zone_around_it():
    labels, windows = ground_truth(dataset([Meme(4.0, 100)]), ROWS, PTS, ignore_window=1.0)
    assert label_of(labels, 104) == IGNORED or label_of(labels, 96) == IGNORED
    assert POSITIVE in labels
    assert label_of(labels, 200) == NEGATIVE
    assert label_of(labels, 8) == NEGATIVE


def test_a_window_without_a_scanned_frame_still_gives_a_positive():
    meme = Meme(1.0, 25, start_ts=0.96, start_frame=24, end_ts=1.04, end_frame=26)
    labels, windows = ground_truth(dataset([meme]), ROWS, PTS)
    assert (labels == POSITIVE).sum() == 1


def test_explicit_not_meme_wins_over_a_window_and_a_neighbours_ignore_zone_never_hides_positives():
    ranged = Meme(2.0, 48, start_ts=1.6, start_frame=40, end_ts=2.4, end_frame=60)
    single = Meme(3.0, 72)
    labels, windows = ground_truth(dataset([ranged, single], [NotMeme(1.92, 48)]), ROWS, PTS)
    assert label_of(labels, 48) == NEGATIVE
    assert label_of(labels, 40) == POSITIVE and label_of(labels, 56) == POSITIVE


def test_auc_and_ties():
    values = np.array([1.0, 2.0, 3.0, 4.0])
    positive = np.array([False, False, True, True])
    assert auc(values, positive) == 1.0
    assert auc(-values, positive) == 0.0
    assert auc(np.ones(4), positive) == 0.5


def test_separable_criterion_has_a_positive_margin_and_a_threshold_in_the_gap():
    values = np.array([1, 2, 3, 10, 11, 12], dtype=float)
    positive = np.array([False] * 3 + [True] * 3)
    report = evaluate_criterion("c", values, positive)
    assert (report.fn, report.fp) == (0, 0)
    assert report.margin == 7 and report.op == ">" and report.threshold == 6.5
    assert (report.safe_low, report.safe_high) == (3, 10)
    assert report.auc == 1.0 and report.normalized_margin > 0 and report.dprime > 5


def test_inverted_criterion_uses_a_less_than_rule_in_its_own_units():
    values = np.array([12, 11, 10, 3, 2, 1], dtype=float)
    positive = np.array([False] * 3 + [True] * 3)
    report = evaluate_criterion("c", values, positive)
    assert report.direction == -1 and report.op == "<" and report.threshold == 6.5
    assert (report.safe_low, report.safe_high) == (3, 10)


def test_overlap_gives_negative_margin_and_the_weighted_cost_prefers_missing_nothing():
    values = np.array([1, 2, 3, 4, 5, 6, 7, 8], dtype=float)
    positive = np.array([False, False, False, True, False, True, True, True])
    report = evaluate_criterion("c", values, positive, fn_weight=10)
    assert report.margin < 0
    assert report.fn == 0 and report.fp == 1  # cut below the overlapping positive, one false positive
    assert evaluate_criterion("c", values, positive, fn_weight=0.1).fn >= 1


def test_best_threshold_prefers_the_widest_gap_on_ties():
    oriented = np.array([0, 1, 10, 11, 20], dtype=float)
    positive = np.array([False, False, True, True, True])
    cut = best_threshold(oriented, positive)
    assert cut.value == 5.5 and cut.gap == 9


def two_criteria_samples(rng=np.random.default_rng(0)) -> Samples:
    """Memes are high in `a` and low in `b`; non-memes are high in one of them but not both."""
    n = 400
    a = np.concatenate([rng.normal(10, 1, n), rng.normal(10, 1, n // 4), rng.normal(0, 1, n)])
    b = np.concatenate([rng.normal(0, 1, n), rng.normal(10, 1, n // 4), rng.normal(0, 1, n)])
    labels = np.concatenate([np.full(n, POSITIVE), np.full(n // 4 + n, NEGATIVE)]).astype(np.int8)
    total = len(labels)
    window = np.where(labels == POSITIVE, np.arange(total) // 4, -1).astype(np.int32)  # memes of 4 frames
    return Samples({"a": a, "b": b, "noise": rng.normal(0, 1, total)}, labels, window, np.full(total, "v"),
                   np.arange(total), np.arange(total) / 3)


def test_search_needs_a_second_criterion_when_one_is_not_enough():
    found = search(two_criteria_samples(), max_conditions=2, max_terms=2)
    assert found[0].score.fp > 50  # `a` alone lets the non-memes with a high `a` through
    best = found[-1]
    assert (best.score.fn, best.score.fp) == (0, 0)
    assert {c.criterion for c in best.rule.conditions()} == {"a", "b"}


def test_search_reports_the_rule_in_code_and_it_evaluates_the_same():
    samples = two_criteria_samples()
    best = search(samples, max_conditions=2, max_terms=1)[-1]
    score, mask = evaluate_rule(eval(repr(best.rule), {"Condition": Condition, "AllOf": AllOf, "AnyOf": AnyOf}), samples)
    assert score == best.score
    assert mask.sum() == (samples.labels == POSITIVE).sum()


def test_search_ignores_ignored_frames_and_holds_out_a_video():
    samples = two_criteria_samples()
    samples.labels[:20] = IGNORED
    samples.video[:] = np.where(np.arange(len(samples.labels)) % 2 == 0, "x", "y")
    train = samples.select(samples.video != "x")
    found = search(train, max_conditions=2, max_terms=1)
    test_score, _ = evaluate_rule(found[-1].rule, samples.select(samples.video == "x"))
    assert test_score.fn == 0 and test_score.fp <= 3


def test_rule_mask_matches_the_rule_classifier_semantics():
    scores = {"a": np.array([1.0, 5.0, 9.0]), "b": np.array([0.0, 0.0, 1.0])}
    rule = AnyOf(AllOf(Condition("a", ">", 4), Condition("b", "<", 0.5)), Condition("a", ">=", 9))
    assert rule_mask(rule, scores).tolist() == [False, True, True]
    assert [rule.evaluate({k: v[i] for k, v in scores.items()}) for i in range(3)] == [False, True, True]


def test_pool_concatenates_videos():
    one = two_criteria_samples()
    both = pool([one, one])
    assert len(both.labels) == 2 * len(one.labels) and set(both.scores) == set(one.scores)


def test_windows_are_numbered_per_meme_and_shared_by_its_frames():
    ranged = Meme(2.0, 48, start_ts=1.6, start_frame=40, end_ts=2.4, end_frame=60)
    single = Meme(5.0, 128)
    labels, windows = ground_truth(dataset([ranged, single]), ROWS, PTS)
    assert {label_of(windows, f) for f in (40, 48, 56)} == {0}
    assert label_of(windows, 128) == 1 and label_of(windows, 200) == -1
    assert (windows >= 0).tolist() == (labels == POSITIVE).tolist()


def test_a_meme_counts_as_found_when_any_of_its_frames_is_detected():
    values = np.array([1, 1, 1, 9, 2, 8, 2, 2, 3], dtype=float)
    positive = np.array([False, False, False, True, True, True, True, False, False])
    windows = np.array([-1, -1, -1, 0, 0, 1, 1, -1, -1])
    by_window = evaluate_criterion("c", values, positive, windows)
    by_frame = evaluate_criterion("c", values, positive)
    assert (by_window.fn, by_window.fp) == (0, 0) and by_window.positives == 2
    assert by_window.margin == 5 and by_window.weakest == 5 and values[by_window.strongest] == 3
    assert by_frame.margin < 0 and by_frame.fn + by_frame.fp > 0


def test_rule_cost_and_missed_memes_use_any_frame_of_the_meme():
    samples = two_criteria_samples()
    first = int(np.flatnonzero(samples.window == 0)[0])
    mask = np.zeros(len(samples.labels), dtype=bool)
    mask[first + 2] = True  # one frame of meme 0 only
    score, _ = evaluate_rule(Condition("a", ">", 1e9), samples)
    assert score.fn == int(samples.window.max()) + 1
    assert first not in missed_memes(samples, mask)
    assert len(missed_memes(samples, mask)) == int(samples.window.max())
    assert len(missed_memes(samples.as_frames(), mask)) == (samples.labels == POSITIVE).sum() - 1


def test_window_judging_finds_cheaper_rules_than_frame_judging():
    samples = two_criteria_samples()
    window_rule = search(samples, max_conditions=1, max_terms=1)[0]
    frame_rule = search(samples.as_frames(), max_conditions=1, max_terms=1)[0]
    assert window_rule.score.cost <= frame_rule.score.cost


def test_window_extremes_are_each_memes_highest_and_lowest_score():
    from tools.evaluation.report import distributions, window_extremes

    samples = two_criteria_samples()
    high, low = window_extremes(samples.scores["a"], samples)
    assert len(high) == len(low) == int(samples.window.max()) + 1
    first = samples.scores["a"][samples.window == 0]
    assert (high[0], low[0]) == (first.max(), first.min()) and (low <= high).all()
    text = distributions(samples)
    assert "meme highs" in text and "meme lows" in text and "non-meme frames" in text
