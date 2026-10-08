---
title: "Edge Black Criterion"
status: implemented
created: 2026-10-07
updated: 2026-10-07
author: ""
depends-on: ["classifier-criteria"]
---

# Edge Black Criterion

## Problem Statement

A glitch card sits in the middle of the frame and its outer edges show dark static crossed by bright
streaks. The existing criteria measure the margins' streaks (`band`, `texture`), their brightness
(`margin_luma`) or their colour (`hue_consistency`). None measures how much of the very edge is
near-black, which the labeled datasets show is tightly bounded for memes (about 28-49%) and very
different for ordinary frames.

## User Story

**Primary:**
As the developer improving the classifier, I want a criterion that scores the share of near-black
pixels on the left and right edges, so that I can study it in the labeler and the evaluator and use
it in rules.

## Acceptance Criteria

- [x] AC1: `extract_memes.criteria` provides `edge_black`: the percentage (0-100) of pixels whose
      brightness is under 5% of the maximum (grayscale below 12.75 of 255) in the outermost 5% of the
      width on the left and on the right (13 px each at the 256-wide scan size), counted together.
- [x] AC2: It follows the criteria rules: one module, registered with `@criterion("edge_black")`,
      scored at the scan size so the result doesn't depend on the video's resolution, with the edge
      geometry (`EDGE_WIDTH`, `edges()`) in `criteria/_common.py`.
- [x] AC3: It appears in the labeler and the evaluator without further wiring.
- [x] AC4: Offline tests cover the percentage on constructed frames, the brightness cut-off, that
      only the edges count, and resolution independence.

## Out of Scope

- Using it in the production classifier. It is a range-type score (memes sit between about 28 and 49),
  so a rule needs both bounds, e.g. `AllOf(Condition("edge_black", ">", 27), Condition("edge_black", "<", 50))`.

## Technical Notes

- Changing `_common.py` changes every criterion's fingerprint, so the labeler's cached scores are
  recomputed once on the next open (and by the evaluator).
- On the two labeled videos: meme frames score 28.3-48.7 (median 37.7); 85% of non-meme frames are
  below 25 and about 14% (2,770 frames) are in 25-50, so it needs a second criterion (with `band`:
  `AllOf(band > 182.4, edge_black > 24.43)` has 0 missed memes and 3 false positives, against 22 for
  `band` alone).

## Open Questions

None.

## Changelog

- 2026-10-07: The user asked for the share of near-black pixels (under 5% brightness) on the outer 5%
  edges as a criterion, after an analysis showed memes cluster at 28-49% there. Implemented it as
  `edge_black` with the edge geometry in `_common`; tests in `tests/test_criteria.py` (424 passed).
