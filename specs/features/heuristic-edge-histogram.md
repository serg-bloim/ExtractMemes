---
title: "Heuristic Classifier Decides on Edge Histogram"
status: implemented
created: 2026-10-08
updated: 2026-10-08
author: ""
depends-on: ["heuristic-classifier", "heuristic-band-only", "classifier-criteria"]
---

# Heuristic Classifier Decides on Edge Histogram

> Amends [heuristic-band-only](heuristic-band-only.md): the production rule is no longer `band > 180`.

## Problem Statement

[heuristic-band-only](heuristic-band-only.md) made `band > 180` the production rule. On the three
labeled videos (291 memes, 32,286 other frames) that threshold flags 247 non-meme frames: 220 of them
score 180–190, right under the cluster of look-alikes. `edge_histogram` measures the same strips (the
outermost 5% on each side) by their whole brightness distribution, and leaves more room: the strongest
non-meme after the 9 frames both criteria disagree with the labels on is 2.57 against a meme maximum
of 1.69, while for `band` it is 201.5 against a meme minimum of 209.9. See the comparison under
Technical Notes.

## User Story

**Primary:**
As a user, I want the production classifier to flag glitch-framed cards with the criterion that
separates them from look-alikes best, so that the extracted memes have fewer false positives.

## Acceptance Criteria

- [x] AC1: `HeuristicClassifier.__init__` takes `edge_histogram_threshold: float = 2.1`, kept as a public
      attribute. `band_threshold` is gone.
- [x] AC2: `is_meme_frame` returns `scores(frame).edge_histogram < edge_histogram_threshold` (strict),
      i.e. the classifier is `RuleClassifier(Condition("edge_histogram", "<", threshold))`.
- [x] AC3: `FrameScores` gains a float field `edge_histogram`, the `edge_histogram` criterion's score;
      `band` and `texture` stay, for diagnostics. `scores()` still scores at 256x144.
- [x] AC4: `is_meme` keeps its contract (unreadable image raises `RuntimeError`; no subprocess, network or
      file written).
- [x] AC5: On `data/labeled_dataset`, every positive frame is flagged and no negative frame is.
- [x] AC6: On the three labeled videos (`python -m tools.evaluation --rule
      'Condition("edge_histogram", "<", 2.1)'`), no meme is missed (window metric) and the non-meme
      frames flagged are no more than the 9 that `band > 205.7` flags too.
- [x] AC7: The offline suite passes (`pytest -m "not slow"`), with the classifier's tests using real
      labeled frames instead of synthetic cards, which the reference histogram doesn't describe.

## Out of Scope

- Changing `band`, `edge_histogram`, or the reference file `criteria/data/edge_histogram.json`.
- Re-checking the 9 frames both criteria flag (probably label noise).
- A held-out (`--holdout`) comparison; the reference is built from these videos' memes, so AC6 is
  in-sample.

## Technical Notes

- Measured 2026-10-08 on the three labeled videos (see classifier-criteria changelog): both criteria catch
  all 369 meme frames and share the same 9 false-positive frames at their best thresholds (`band > 205.7`,
  `edge_histogram < 2.127`); after those, the gap is 8.4 for `band` and 0.88 for `edge_histogram`.
  Threshold 2.1 lies in the safe interval (1.682, 2.572) the evaluation tool reports.
- `edge_histogram` needs `criteria/data/edge_histogram.json` (shipped as package data) and so is not
  parameter-free like `band`; a video with a different card style may need the reference rebuilt
  (`python -m tools.evaluation.build_template edge_histogram`).

## Open Questions

- [ ] Q1: Should an ADR record the switch? (decision point per CLAUDE.md)

## Changelog

- 2026-10-08: The user asked to change production to `edge_histogram` after comparing it with `band`.
  Drafted this spec and implemented it in the same step.
  Checked: `pytest -m "not slow"`: 476 passed. `python -m tools.evaluation --rule
  'Condition("edge_histogram", "<", 2.1)'` on the three labeled videos: 0 memes missed, 9 false-positive
  frames (the same 9 as `band > 205.7`). Tests of the classifier now use real labeled frames; the
  synthetic card no longer scores as a card. The labeler's stored verdicts and its page thresholds
  follow the new rule (it re-scores a video's verdicts the next time it opens it); the scene database
  still holds the old verdict-related stats until videos are populated again.
