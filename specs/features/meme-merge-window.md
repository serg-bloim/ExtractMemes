---
title: "Merge Consecutive Flagged Frames (--merge-window)"
status: implemented
created: 2026-10-05
updated: 2026-10-05
author: ""
depends-on: ["extraction-pipeline", "batch-cleaning", "meme-timecodes", "no-images"]
---

# Merge Consecutive Flagged Frames (`--merge-window`)

## Problem Statement

A meme card that stays on screen for longer than the scan interval is flagged in several
consecutive samples (at the default 2 fps, a 1.5 s card yields about three). The pipeline turns
every flagged sample into its own meme: each gets a `meme_<n>` number, its own ±`window_seconds`
extraction window, its own `clean/meme_<n>.png`, its own timecode line and its own upload. The
windows overlap, so one card comes out as several near-identical images and timecodes. This is the
open issue 44 in [ADR 007](../../decisions/007-documentation-consolidation-for-rebuild.md) and the
deferred dedup item in [extraction-pipeline](extraction-pipeline.md) Out of Scope.

## Amends

This is an iteration spec. It applies after [extraction-pipeline](extraction-pipeline.md). Once it
is `implemented`, these criteria read as amended here:

| Earlier spec | Criterion | Amended by |
|---|---|---|
| [extraction-pipeline](extraction-pipeline.md) | Each flagged timestamp becomes one batch with its own ±`window_seconds` window | AC1, AC3 |
| [meme-timecodes](meme-timecodes.md) | One timecode line per meme | AC1 (a meme is now a merged run of flagged samples) |
| [no-images](no-images.md) | Timecodes come from the flagged scan timestamps | AC5 |

Not amended: sampling, classification, `--save-frames` and `--save-low-res`. The scan still
writes one low-res file per flagged sample; merging happens after the scan, on the list of flagged
timestamps.

## User Story

**Primary:**
As a user, I want flagged frames that are close together in time to count as one meme, so that a
card that stays on screen for a while produces one image and one timecode instead of several
near-duplicates.

## Acceptance Criteria

- [x] AC1: While scanning, a flagged frame whose timestamp is within `merge_window` seconds of the
      **first** flagged frame of the most recent meme joins that meme. Otherwise it starts a new
      meme. A meme therefore spans at most `merge_window` seconds of flagged frames; a longer
      card is split into several memes, deliberately, since a long meme is not expected.
- [x] AC2: The comparison uses the gap between the two flagged frames' own timestamps, and is
      inclusive: a gap equal to `merge_window` merges.
- [x] AC3: A merged meme is extracted once. Its extraction window runs from `window_seconds`
      before its first flagged frame to `window_seconds` after its last. Every frame in that
      window is classified, and the accepted ones form the meme's single batch.
- [x] AC4: Memes are numbered in video order with no gaps, one `meme_<n:03d>` per merged meme,
      for `clean/` and `high-res/` alike.
- [x] AC5: Each meme gets one timecode line, and its time comes from its earliest accepted batch
      frame as before. With `--no-images`, it is the first flagged scan timestamp of the merged
      meme.
- [x] AC6: `--merge-window SECONDS` sets the window; the `merge_window` parameter on `pipeline.run`
      does the same. The default is `1.0`.
- [x] AC7: `--merge-window 0` turns merging off, so each flagged frame is its own meme, as before
      this spec. A negative value is rejected with `parser.error` on the CLI and a `ValueError`
      from `run`.
- [x] AC8: Unflagged samples in between do not matter. Only the timestamps of flagged frames are
      compared, so an unflagged sample inside the window does not split a meme.
- [x] AC9: The upload and the timecode sender receive the merged results: one image and one
      timecode per merged meme.
- [x] AC10: Tests cover: a run of close flagged frames giving one meme; two runs further apart than
      the window giving two; the inclusive boundary (AC2); a run longer than the window being split
      from its first frame (AC1); the extended window (AC3); `0` disabling merging; the negative-value
      rejection; the `--no-images` timecode (AC5); and the CLI wiring. They use a fake classifier
      and a synthetic video, never the real `claude` CLI.

## Out of Scope

- Perceptual or pixel-level dedup of near-identical frames (ADR 002 M7). This spec merges by time
  only. The same card shown again later in the video is a separate meme.
- Merging the `--save-low-res` files. They stay one per flagged sample.
- Changing `--fps` or the classifier.
- Automatically choosing the window from the video's content.

## Technical Notes

- The window is anchored at the meme's first flagged frame and never slides, so a meme's last
  flagged frame is at most `merge_window` after its first.
- Merging needs only the ordered `(index, timestamp)` list the scan already builds in `flagged`.
  Grouping can happen on the fly in the scan loop or right after it, with the same result.
- `count` in the extraction loop is currently a constant `2 * window_seconds * native_fps + 1`.
  It becomes per meme, from the merged span.
- The merge window and the extraction `window_seconds` are separate settings. With the defaults
  they are equal (1 s), but changing one does not change the other.
- If `merge_window` is shorter than the sampling interval (`1 / fps`), two consecutive samples are
  never close enough to merge, so it behaves like `0`. That is expected, not an error.
- No new dependencies.

## Open Questions

Resolved by the user (2026-10-05):

- Q1: Measure from the meme's last flagged frame or its first? **From the first** (AC1). No long
  memes are expected, so a run that outlasts the window is better split than silently merged into
  one long, possibly erroneous meme.
- Q2: Print a merge summary line? **No.**

## Changelog

- 2026-10-05: The user asked for a fix to the same card being captured several times when it
  lasts longer than the scan interval: a newly flagged frame within a configurable merge window
  (1 s by default) of the last captured meme should merge into it. Drafted this spec as an
  iteration on [extraction-pipeline](extraction-pipeline.md). Status `draft`, awaiting review
  of Q1–Q2.
- 2026-10-05: Q1–Q2 answered by the user: measure from the meme's first flagged frame (AC1, AC3,
  AC8 and the Technical notes reworded to match), and no summary line. Status `ready`.
- 2026-10-05: Implemented.
  - **Pipeline:** `merge_window` parameter on `run` (default 1.0, negative raises `ValueError`).
    The scan loop now keeps one `(first, last)` flagged-timestamp pair per meme and extends the
    latest while a new flagged frame is within `merge_window` of its first. Extraction reads
    `last - first + 2 * window_seconds` seconds of frames per meme, from `window_seconds` before
    the first flagged frame; the frame count still ignores the clamp at 0 s, so an unmerged meme
    reads the same frames as before.
  - **CLI:** `--merge-window SECONDS`, rejecting negative values with `parser.error`.
  - **Tests:** merging, the first-frame anchor, the inclusive boundary, `0`, the extended
    window, separate extraction without merging, one upload/timecode per merged meme, the
    negative-value rejection, and the CLI wiring.
  - **Verified:** `pytest -m "not slow"` passes.
