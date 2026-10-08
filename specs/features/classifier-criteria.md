---
title: "Classifier Criteria and Rules"
status: implemented
created: 2026-10-07
updated: 2026-10-07
author: ""
depends-on: ["heuristic-classifier", "heuristic-band-only"]
---

# Classifier Criteria and Rules

## Problem Statement

The heuristic classifier's scoring lives inside `HeuristicClassifier`, and the labeler's candidate
criteria (`margin_luma`, `hue_consistency`) lived in a second copy of the margin geometry under
`tools/`. The numbers shown while labeling could therefore drift from the ones the pipeline computes,
and trying a new criterion, or combining several into a better classifier, meant editing a class and
hand-wiring the tools. The criteria should live in one place in the main code, be added one file at a
time, be combined by rules, and show up in the labeler without any extra step.

## User Story

**Primary:**
As the developer improving the classifier, I want every criterion defined once in the main code, a
way to combine criteria into a classifier, and the labeler to show exactly those criteria, so that
the scores I study while labeling are the scores the pipeline uses, and a new criterion appears in
the labeler as soon as I add it.

## Acceptance Criteria

- [x] AC1: Criteria live in the package `extract_memes.criteria`, one module per criterion. A module
      registers its criterion with `@criterion("name")`, and `all_criteria()` imports every public
      module of the package and returns them by name (in name order). Adding a criterion is adding a
      file; nothing else is edited.
- [x] AC2: A criterion is a function from a BGR frame of any size to a float, and its score does not
      depend on the frame's resolution: shared code in `criteria/_common.py` brings every frame to
      the scan size (256x144) first. The constants of that geometry exist only there.
- [x] AC3: The package provides `band`, `texture`, `margin_luma` and `hue_consistency`.
      `HeuristicClassifier.scores()` returns the `band` and `texture` criteria's scores, so the old
      numbers are unchanged.
- [x] AC4: `extract_memes.rule_classifier` provides `Condition(criterion, op, value)` (op one of
      `> >= < <=`), `AllOf(...)` and `AnyOf(...)`, which nest, and `RuleClassifier(rule)`, a
      `FrameClassifier` that computes only the criteria its rule uses, once per frame. A rule naming
      a criterion that doesn't exist fails when the classifier is built.
- [x] AC5: `HeuristicClassifier` is `RuleClassifier(Condition("band", ">", band_threshold))` and
      behaves as before: its constructor, `band_threshold` attribute, `scores()`, `is_meme_frame`
      and `is_meme` are as specified in [heuristic-classifier](heuristic-classifier.md) and
      [heuristic-band-only](heuristic-band-only.md), and the pipeline still constructs
      `HeuristicClassifier()`.
- [x] AC6: A `Criterion` has a `fingerprint()` that changes when its module or `_common` changes,
      and a `RuleClassifier` has a `fingerprint()` that changes with the rule and with the
      fingerprints of the criteria it uses, so anything cached from them can be invalidated.
- [x] AC7: The labeler uses these and nothing of its own: it lists `all_criteria()`, takes its
      verdict from `HeuristicClassifier()` (what the pipeline runs), draws the thresholds that
      classifier's rule compares each criterion with, and its scores equal what the pipeline's scan
      (`sample_frames` and the same criteria functions) computes for the same frames. A criterion
      file added while `./labeler.sh` runs appears in the labeler (metric list, filters, strip,
      histogram) after the automatic restart, with its scores computed on the way.
- [x] AC8: Importing `extract_memes.criteria` or `extract_memes.rule_classifier` does no work and
      touches nothing outside memory (the criterion modules are imported by `all_criteria()` /
      `get()`), and adds no dependency to `[project.dependencies]`.
- [x] AC9: Offline tests cover discovery (including a module dropped into the package), duplicate
      names, resolution independence, the fingerprints, conditions, combinations, the
      only-needed-criteria rule, and the labeler's scores matching the scan's.

## Out of Scope

- Choosing a different production classifier from the CLI or configuration (the pipeline still uses
  `HeuristicClassifier()`); adopting a combined rule in production is a separate, specced change.
- Showing the verdict of several candidate rules side by side in the labeler, and searching for good
  rules and thresholds over a dataset (the evaluation spec this subproject was started for).
- Criteria that need more than the one frame (neighbouring frames, audio).

## Technical Notes

- Convention for a criterion module, which keeps its fingerprint honest: one criterion plus private
  helpers, and shared code only from `_common` (the fingerprint hashes the module's file and
  `_common.py`). A module that imports another criterion module would not be re-scored when that
  other module changes.
- To try a combination in code: `RuleClassifier(AllOf(Condition("band", ">", 180), Condition("margin_luma", "<", 35)))`.
  The labeler currently shows the verdict of `HeuristicClassifier()`; change that class's rule (or
  pass another classifier to `tools.labeling.index.build`) to see a combination there.
- Flask's own reloader doesn't notice a newly created file, so `labeler.sh` uses `watchfiles` around
  Flask's server and restarts on any Python change under `src/extract_memes/` or `tools/labeling/`.
- `labeling` extra now also holds `watchfiles`.

## Open Questions

Resolved by the user's request (2026-10-07):

- Where do the criteria live? **In the main code, once; the labeler reuses them without copying.**
- How are they extended? **Modularly, one new file per criterion, discovered automatically, and
  combined by rules.**
- What does the labeler show? **The same criteria, including newly added ones.**

## Changelog

- 2026-10-07: The user asked for all criterion code in one place in the main codebase, reused by the
  labeler without copying, modular and combinable, with new criteria visible in the labeler. Wrote
  this spec and implemented it: `extract_memes/criteria/` (`_common`, `band`, `texture`,
  `margin_luma`, `hue_consistency`), `extract_memes/rule_classifier.py`, `HeuristicClassifier` as a
  `RuleClassifier`; `tools/labeling/criteria.py` was deleted and the labeler reads the package.
  `pytest -m "not slow"`: 359 passed. A probe criterion file dropped into the package while
  `labeler.sh` ran showed up in the labeler with its scores and left again when deleted.
- 2026-10-08: The user asked `band` to take 5% from each side instead of the 20% margins. It now reads
  the outermost 5% of the width on each side (`edges()`, as `edge_black` and `edge_histogram` do); the
  other criteria still use `margins()`. The rule `band > 180` is unchanged. Measured on the 38 frames
  of `data/labeled_dataset`: cards 228.1–234.2 (were 230.3–235.7), non-cards 0–88.0 (were 0–124.4),
  so the threshold still separates them (15/15 caught, 0/23 false positives). `pytest -m "not slow"`:
  475 passed. Stored `band` stats in the scene database predate this and are stale until the videos
  are populated again; the labeler recomputes `band` for a video the next time it opens it.
- 2026-10-08: `HeuristicClassifier` is now `RuleClassifier(Condition("edge_histogram", "<", 2.1))` and
  `FrameScores` gains `edge_histogram` ([heuristic-edge-histogram](heuristic-edge-histogram.md)); this amends AC5's
  "behaves as before" for the rule and the constructor (`edge_histogram_threshold`).
