---
title: "Criteria Evaluation and Combination Search"
status: implemented
created: 2026-10-07
updated: 2026-10-07
author: ""
depends-on: ["classifier-criteria", "labeled-video-dataset", "frame-labeler"]
---

# Criteria Evaluation and Combination Search

## Problem Statement

There are now hand-labeled datasets (`data/datasets/*.yaml`) and several criteria
(`extract_memes.criteria`: `band`, `texture`, `margin_luma`, `hue_consistency`, more to come). Judging a
criterion today means eyeballing histograms in the labeler. There is no way to say, for each
criterion, how many false positives and false negatives it makes at its best threshold, how cleanly
it separates memes from non-memes (how much room there is around the threshold before it breaks), or
which small set of criteria together covers every labeled case. Picking a production rule is guesswork.

## User Story

**Primary:**
As the developer improving the classifier, I want a report that scores every criterion against all
labeled datasets (errors, separation, confidence gap) and searches for the smallest combination of
criteria that classifies the labeled frames correctly, so that I can choose a production rule from
numbers instead of by eye.

## Terminology

The "gap between class A and class B by the metric" is the **separation margin** (the SVM term:
the width of the empty corridor around the decision threshold). Related, standard measures:

| Measure | Meaning |
|---|---|
| **Margin** | `min(positive scores) - max(negative scores)` (sign flipped if positives score lower). Positive = perfectly separable with that much room; negative = the classes overlap by that much. |
| **Robust margin** | The same with the 1st/99th percentiles instead of min/max, so one mislabeled frame doesn't zero it. |
| **Normalized margin** | Margin divided by the criterion's overall spread (e.g. its interquartile range), so criteria with different scales can be compared. |
| **AUC** | Probability that a random positive outscores a random negative (0.5 = useless, 1.0 = perfectly separable, threshold-free). |
| **d′ (d-prime)** | Distance between the class means in units of their pooled standard deviation. |

## Acceptance Criteria

- [x] AC1: Ground truth per scanned frame comes from the dataset: **positive** = a frame inside a
      marked meme's window (`meme_start_*`..`meme_end_*`), **negative** = every other scanned frame
      (and every explicit `not_memes` frame, which wins over a window it lies in). There is no
      "unlabeled" zone. The one exception is a meme marked with a single frame and no window (its
      extent is unknown): its marked frame is positive and the scanned frames within ±1.0 s of it
      are ignored rather than called negatives; the report counts them. All datasets in
      `data/datasets/` are pooled by default; a subset can be chosen.
- [x] AC2: Criterion scores are read from the labeler's cache (`.runtime/labeler/<video>_<format>/`),
      which is built/refreshed with the existing cache machinery, so the evaluator never scores a
      frame differently from the pipeline, and a changed criterion is re-scored automatically (its
      fingerprint).
- [x] AC11: **Window metric** (default, `--metric window`): a meme is found when at least one of its
      frames is detected; a false negative is a meme with no detected frame, a false positive is still a
      non-meme frame. A criterion is judged by each meme's best frame against every non-meme frame, so
      its margin, AUC, d′ and threshold gap are between those. `--metric frame` keeps the earlier
      every-frame-of-the-meme judging. Rule search, refinement of thresholds and the error lists use
      the same metric. The report adds a separation table naming, per criterion, the weakest meme and
      the strongest non-meme (video, time) that limit the gap.
- [x] AC12: `--distributions` prints, per criterion and in the criterion's own units, each meme's
      highest and lowest score over its frames (one pair per meme) and the scores of the non-meme
      frames: min, percentiles (1, 5, 25, 50, 75, 95, 99), max and a histogram on shared bins, so the
      three spreads can be compared. A meme marked with one frame has equal high and low.
- [x] AC3: For each criterion the report gives: counts of positives/negatives used; the direction
      (does a meme score higher or lower) found from the data; the best single threshold (lowest
      weighted cost `fn_weight * FN + FP`, ties broken toward the widest margin; `fn_weight` defaults
      to 10 because a missed meme is a silent error while a false positive is caught on review) with its **false positives**, **false
      negatives**, precision and recall; the margin, robust margin, normalized margin, AUC and d′
      defined in Terminology; and the safe interval (the threshold range that keeps the errors
      unchanged).
- [x] AC4: The report can list the actual misclassified frames per criterion (video id, frame index,
      timestamp), so a false positive can be opened in the labeler.
- [x] AC5: Criteria are ranked by a chosen metric (default: errors, then robust margin) and the table
      is printed as text; `--csv`/`--json` output is available for further analysis.
- [x] AC6: **Combination search**: over rules built from `Condition`, `AllOf` and `AnyOf`
      ([classifier-criteria](classifier-criteria.md)), find rules with zero false negatives first, then the fewest
      false positives, using the fewest criteria (same weighted cost as AC3). Thresholds are chosen per criterion (max-margin
      placement inside the safe interval, not at the edge of the data). Search is bounded (size
      limit `k`, default 3) and reports the best rule for each size 1..k with its FP/FN and the margin
      of each of its thresholds, so the cost of adding a criterion is visible.
- [x] AC7: A found rule is reported in a form that pastes straight into code
      (`AllOf(Condition("band", ">", 180), ...)`) and can be evaluated again with the same report
      (a rule given on the command line gets the AC3/AC4 numbers).
- [x] AC8: Overfitting is visible: the search can hold out one video (train on the others, test on
      it) and the report shows train vs. held-out errors.
- [x] AC9: The evaluator is dev tooling under `tools/` (no changes to `src/extract_memes/`, no new
      runtime dependencies; numpy only, plus whatever the `labeling` extra already has). Importing it
      has no side effects.
- [x] AC10: Offline tests cover the ground-truth derivation, each metric on synthetic scores
      (separable, overlapping, inverted direction), threshold selection, the combination search on
      a synthetic problem where one criterion is not enough, and hold-out. No test needs network or
      the real videos.

## Out of Scope

- Changing the production classifier (adopting a found rule is a separate, specced change).
- Learned models (trees, logistic regression); only the existing rule vocabulary for now.
- Criteria needing more than one frame.
- A graphical front end (see Open Questions).

## Technical Notes

- Suggested layout: `tools/evaluation/` (`truth.py` ground truth, `metrics.py` per-criterion
  measures, `search.py` rule search, `__main__.py` CLI: `python -m tools.evaluation [--dataset ID ...]
  [--max-size K] [--holdout ID] [--rule '...']`).
- Candidate thresholds for a criterion are the midpoints between consecutive distinct sorted scores,
  so a per-criterion sweep is one sort plus cumulative sums (O(n log n)). Pair/triple combinations
  with `AllOf` and `AnyOf` reuse boolean vectors of "frame passes condition" and can be searched
  exhaustively over a thinned threshold set (e.g. quantiles), or greedily (set-cover style: add the
  condition that removes most remaining errors) when the exhaustive space is too big.
- Class imbalance is large (few memes among tens of thousands of negatives), so errors are reported
  as counts, never only as accuracy.
- Memes marked with a single frame in standard mode have unknown extent, so positives from those
  videos are few and their neighbours are unlabeled; ranged memes (`meme_start_*`/`meme_end_*`)
  give many more positives. The report states how many of each it used.

## Open Questions

Resolved by the user (2026-10-07):

- Q1: Positives? **All frames inside a meme's window are positives, all outside are negatives** (AC1;
  for single-frame marks without a window the extent is unknown, so they keep a ±1 s ignore zone —
  interpretation to confirm).
- Q3: Error weighting? **A missed meme is worse** (it is a silent error; a junk image is caught on
  review) — AC3/AC6 weight false negatives by default.
- Q2 (output form): command line text/CSV/JSON only, for now.
- Q4 (strict second view): dropped; there is no unlabeled zone except the single-frame case above.

## Changelog

- 2026-10-07: The user asked for a system to analyze criteria against the labeled datasets (false
  positives/negatives, how wide the gap between classes is, a name for that measure) and to search
  for a minimal, effective combination of criteria. Drafted this spec (status `draft`); named the
  gap "separation margin"; awaiting review and answers to the open questions.
- 2026-10-07: The user answered: all frames in a window are positives and all outside negatives; a
  missed meme is worse than a false positive. Spec updated (AC1, AC3, AC6) and set `in-progress`.
- 2026-10-07: Implemented in `tools/evaluation/` (`truth`, `data`, `metrics`, `search`, `report`,
  `__main__`; run `python -m tools.evaluation`). Search is a beam search over threshold conditions
  with sequential covering into `AnyOf(AllOf(...))`, then each threshold is moved to the middle of its
  widest gap (rounded to 4 significant digits when that stays inside the gap). Weighted cost uses
  `--fn-weight` (default 10). `--rule` evaluates a rule given as text with only `Condition`/`AllOf`/`AnyOf`
  in scope. `tests/test_evaluation.py`: 14 tests. On the two labeled videos the best single criterion
  is `band > 187.5` (FN 1, FP 24); `AllOf(band > 176.6, hue_consistency < 0.6021)` has FN 0, FP 5.
- 2026-10-07: The user asked for a different success metric (each meme window needs at least one
  detected frame) and to see how wide the separation gaps are. Added AC11 (window metric as the
  default, frame metric kept as an option) and the separation table; positives now carry a meme number
  (`ground_truth` returns labels and windows, `Samples.window`), FN counts memes, the per-criterion
  precision column became FP rate. On the two videos `band > 187.5` alone now misses no meme (FP 24);
  its gap is -45 (weakest meme peak 188.5 vs a non-meme at 234.1, FtU4MuksCzE 2569.92s), so no
  threshold is clean. `AnyOf(AllOf(band > 178.6, hue_consistency < 0.6226), band > 215.4)`: FN 0, FP 5,
  threshold gaps 31.8 (band) and 0.29 (hue_consistency).
- 2026-10-07: The user asked, per criterion, for the distribution of the memes' highs, the memes'
  lows and the non-memes' scores. Added AC12 and `--distributions`. Non-memes have no windows, so
  their spread is that of all non-meme frames (its extremes are their high and low). On the two videos
  `band`: meme highs 188.5-236.5 (p5 215.5), meme lows 184.3-236.5, non-meme frames 0-234.1 (p99 177.4).
