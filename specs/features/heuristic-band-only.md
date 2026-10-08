---
title: "Heuristic Classifier Decides on Band Only"
status: implemented
created: 2026-10-05
updated: 2026-10-05
author: ""
depends-on: ["heuristic-classifier"]
---

# Heuristic Classifier Decides on Band Only

> **Amended by [heuristic-edge-histogram](heuristic-edge-histogram.md):** the production rule is now
> `edge_histogram < 2.1`; `band_threshold` is replaced by `edge_histogram_threshold`.

## Problem Statement

[heuristic-classifier](heuristic-classifier.md) flags a frame when `band > 180` **and**
`texture > 18`. Looking at the whole of `Ij427pW96aI` (46,988 frames), the texture test turns out
to reject real cards without ever rejecting anything the band test lets through: the band score is
bimodal, with 541 frames at 220.6 or above and none between 180 and 220, yet only 445 of those 541
pass the texture test. The other 96, in 37 short runs, are card-like frames (visually checked by
the user) that get missed. Texture also hovers near its threshold on a real card (from 13.8 to
24.2 across the six frames of one card at 323 s), so whether a card is found depends on which frame
the scan samples. On the labeled set, band alone gives the same result as the pair.

## Amends

This is an iteration spec (ADR 008, Decision 4). Once it is `implemented`, these criteria of
[heuristic-classifier](heuristic-classifier.md) read as amended here:

| Earlier spec | Criterion | Amended by |
|---|---|---|
| [heuristic-classifier](heuristic-classifier.md) | AC1: constructor takes `band_threshold` and `texture_threshold` | AC1 |
| [heuristic-classifier](heuristic-classifier.md) | AC3: `is_meme_frame` is `band > band_threshold and texture > texture_threshold` | AC2 |
| [heuristic-classifier](heuristic-classifier.md) | AC8: the flat-background (texture guard) case is `False` | AC5 |
| [heuristic-classifier](heuristic-classifier.md) | AC11: the exact result for `sample/short.mp4` | AC6 (must still hold) |

Not amended: `scores()` (AC2 of the earlier spec, including how `texture` is computed), `is_meme`
(AC4), the pipeline and CLI wiring (AC5, AC6) and the playground's labeled-set check (AC7).

## User Story

**Primary:**
As a user, I want the heuristic to flag every glitch-framed card whose margins have the bright
bands, so that cards whose static happens to score low on texture aren't missed.

## Acceptance Criteria

- [x] AC1: `HeuristicClassifier.__init__` takes only `band_threshold: float = 180.0`, kept as a
      public attribute. `texture_threshold` and the `texture_threshold` attribute are removed.
- [x] AC2: `is_meme_frame` returns `scores(frame).band > band_threshold` (strict). The texture
      score plays no part in the decision.
- [x] AC3: `scores()` and `FrameScores` are unchanged, so `texture` is still computed and returned
      for diagnostics (the playground reports and `test_score_labeled_set`).
- [x] AC4: On the labeled set, every `positive/*.png` is `True` and every `negative/*.png` is
      `False`, as before. `sample/quick_frame_9-32.png` is still `True`.
- [x] AC5: In `tests/test_heuristic_classifier.py`, the case "the band and card on a flat dark-gray
      background" now expects `True`, with a comment that texture no longer guards it. The
      `band_threshold=1000.0` case drops its `texture_threshold` argument and assertion.
- [x] AC6: `run("sample/short.mp4", …)` with the defaults still returns exactly
      `frame_000264_10.56s.jpg` and `frame_000720_28.80s.jpg` (earlier AC11), checked by
      `test_default_run_finds_exactly_the_known_memes`.
- [x] AC7: Measured, and recorded in the Changelog, on `Ij427pW96aI_worst.mp4` (every frame, from
      `.runtime/downloads/`): the number of frames flagged is 541 (it was 445), and every frame
      with `band > 180` is at least 220 (the gap that makes the threshold safe).
- [x] AC8: `playground/playground.py`'s `test_score_labeled_set` still prints `band` and
      `texture`, and its verdicts use the new rule. `playground/criteria_report.py` and the two
      report scripts no longer read `classifier.texture_threshold`: they show `texture` as a plain
      number with no pass/fail mark, and their "kept" rules are written with the band test only or
      with a fixed value they define themselves.
- [x] AC9: The earlier spec's header and Technical Notes get a pointer to this spec, and ADR 008
      register item 60 (texture used as a guard) is marked resolved by it.

## Out of Scope

- Changing `band_threshold` or how `band` is computed.
- Removing the `texture` computation or the `texture` field of `FrameScores`.
- Looking at the 374 frames with `band` 100–140 and the 9 with 140–180, which are well under the
  threshold and not flagged either way.
- A CLI flag for the threshold (the earlier spec's Out of Scope still applies).
- Validation on videos other than `Ij427pW96aI`, `sample/short.mp4` and the labeled set.

## Technical Notes

- **Measured (2026-10-05).** Labeled set (15 cards, 23 others): band only 15/15 caught and 0/23
  false positives, the same as band plus texture; texture alone 15/15 with 2/23 false positives.
  Cards' band is 230.9–235.1 (5th to 95th percentile) and the others' is up to 95.9.
  `Ij427pW96aI`, every frame: band 0–100 → 46,064 frames, 100–140 → 374, 140–180 → 9, 180–220 →
  0, 220 and above → 541. Of the 541, 445 pass texture and 96 don't.
- **What this gives up.** The earlier spec kept texture as "a guard against a bright bar on a
  smooth background". With band alone, a frame with bright rows in its margins and nothing else
  is flagged. No frame in the video or the labeled set does that (nothing falls between band 180
  and 220), but the synthetic test in AC5 shows the case exists in principle.
- **The 96 frames:** 37 runs of 1–6 frames, such as 5:22.96–5:23.20, 7:34, 7:43, 38:53 and
  43:43. They look like cards whose static has less saturation variation. The user has looked at
  them; this spec's author hasn't verified each one.
- No new dependency.

## Open Questions

Resolved with the defaults the draft proposed when the user answered "go" (2026-10-05):

- Q1: Keep computing `texture`? **Yes** (AC3).
- Q2: An ADR? **No.** This spec and the ADR 008 register note (AC9) record it.

## Changelog

- 2026-10-05: The user compared the frames the heuristic passes on texture only with those it
  passes on band only (both `playground/*_report/`), and judged the texture test irrelevant, with
  false positives and false negatives. Checked it: texture can't add false positives when
  combined with band by AND, but it does reject 96 card-like frames in `Ij427pW96aI`, and the
  labeled set gets the same result from band alone. The user asked for the spec change; drafted
  this spec. Status `draft`, awaiting review of Q1–Q2.
- 2026-10-05: The user said to go ahead, which adopted the draft's answers to Q1–Q2. Implemented.
  - **Classifier:** `HeuristicClassifier(band_threshold=180.0)` only; `is_meme_frame` is
    `scores(frame).band > band_threshold`. `scores()` and `FrameScores` are unchanged.
  - **Tests:** the flat-background case now expects `True`, and the threshold test drops
    `texture_threshold`.
  - **Playground:** `frame_report.py`, `criteria_report.py` and the two report scripts no longer
    read `classifier.texture_threshold`; the two "only" reports define `TEXTURE_THRESHOLD = 18.0`
    themselves. `test_score_labeled_set` gives 38/38 correct.
  - **Docs:** pointer added to [heuristic-classifier](heuristic-classifier.md); ADR 008 register
    item 60 marked resolved.
  - **Measured (AC7):** on every frame of `Ij427pW96aI_worst.mp4` (46,988), 541 frames are flagged
    (445 before) and the lowest flagged band is 220.6. `pytest -m "not slow"`: 255 passed.
- 2026-10-08: `band` now measures the outermost 5% on each side instead of the 20% margins (see
  [classifier-criteria](classifier-criteria.md) changelog); the threshold stays 180.
- 2026-10-08: Superseded as the production rule by [heuristic-edge-histogram](heuristic-edge-histogram.md).
