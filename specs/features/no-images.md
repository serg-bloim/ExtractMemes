---
title: "Timecodes-Only Runs (--no-images)"
status: implemented
created: 2026-09-17
updated: 2026-09-17
author: ""
depends-on: ["extraction-pipeline", "batch-cleaning", "meme-timecodes"]
---

# Timecodes-Only Runs (`--no-images`)

## Problem Statement

A user who only wants the list of timecodes still pays for the whole extraction half of the run:
the source video is downloaded a second time at best quality — by far the slowest, largest step —
every meme's ±1 s window is decoded and re-classified, and a cleaned image is written for each
meme. Today there is no way to stop that: `--clean-method none` without `--save-high-res` is
rejected outright ("nothing would be saved"), so the cheapest run that yields
[timecodes](meme-timecodes.md) is a full one.

## Amends

This is an iteration spec. It applies after [meme-timecodes](meme-timecodes.md). Once this spec is
`implemented`, these acceptance criteria read as amended here, **but only when `no_images` is set**
— a run without it is unchanged in every respect.

| Earlier spec | Criterion | Amended by |
|---|---|---|
| [meme-timecodes](meme-timecodes.md) | AC2: a meme's start is the earliest accepted batch frame | AC3 |
| [meme-timecodes](meme-timecodes.md) | AC3: one line per meme that produced an accepted frame | AC3 |
| [extraction-pipeline](extraction-pipeline.md) | The best-quality download and extraction pass | AC2 |
| [batch-cleaning](batch-cleaning.md) | `clean/meme_<n>.png` per meme | AC2 |

Not amended: the scan half of the run — sampling, classification, `--save-frames`, and
`--save-low-res` all behave exactly as before.

## User Story

**Primary:**
As a user who only wants the timecodes of the memes in a video, I want to skip image generation
entirely, so that the run finishes in seconds without downloading the video at best quality.

## Acceptance Criteria

### Pipeline

- [x] AC1: `pipeline.run` gains a trailing keyword parameter `no_images: bool = False`. All other
      parameters and their defaults are unchanged.
- [x] AC2: With `no_images=True`, the run ends after the scan: `download(source, "best", …)` is
      never called, no frame is read from a best-quality copy, and no `clean/`, `high-res/`, or
      `clean/meme_*.png` is created or written. `run` returns `[]`.
- [x] AC3: With `no_images=True` and `save_timecodes=True`, `timecodes.txt` has one line per
      **flagged scan frame**, in scan order, numbered `Мем 1 … Мем N`. A line's start time is
      that frame's scan timestamp, shifted and clamped by `timecode_offset` exactly as in
      meme-timecodes AC5, and formatted as in meme-timecodes AC4.
- [x] AC4: `no_images=True` requires something to be saved: it raises `ValueError` before creating
      anything unless at least one of `save_timecodes`, `save_low_res`, or `save_frames` is set.
- [x] AC5: `no_images=True` together with `save_high_res=True` raises `ValueError` before creating
      anything — the two contradict each other. `clean_method` is ignored instead (it has a
      non-`None` default, so it cannot say whether the user asked for cleaning), and the
      "nothing would be saved" check on `clean_method=None` is skipped.
- [x] AC6: With `no_images=True`, `run` creates only the folders the scan options ask for:
      `frames/` with `save_frames`, `low-res/` with `save_low_res`, and nothing else. The run
      folder itself is created when `timecodes.txt` is written.
- [x] AC7: When nothing is flagged, `run` prints `No memes found.` and returns `[]`, and writes no
      `timecodes.txt`, exactly as in meme-timecodes AC7.
- [x] AC8: Whenever `run` writes `timecodes.txt` — with or without `no_images` — it prints
      `Wrote <N> timecodes to <path>`, so a run that saves no images still reports what it did.

### CLI

- [x] AC9: The CLI adds `--no-images` (a `store_true` flag, off by default), passed as
      `no_images`. Its help text says the run stops after the scan, skips the best-quality
      download, and is meant to be paired with `--save-timecodes`.
- [x] AC10: `--no-images --save-high-res` is rejected by argparse itself with exit code 2, rather
      than reaching the pipeline.

### Tests

- [x] AC11: `tests/test_pipeline.py`: a local `no_images=True` run with `save_timecodes=True`
      returns `[]`, calls `download` only with `"worst"`, creates no `clean/` or `high-res/`, and
      writes one `timecodes.txt` line per flagged scan frame.
- [x] AC12: `tests/test_pipeline.py`: `no_images=True` with nothing to save, and with
      `save_high_res=True`, each raise `ValueError` and leave the runtime dir untouched.
- [x] AC13: `tests/test_pipeline.py`: a `no_images` run with `save_frames=True` and
      `save_low_res=True` writes both folders and no others; `timecode_offset` still shifts the
      lines.
- [x] AC14: `tests/test_cli.py`: the CLI passes `no_images=False` by default and `True` with
      `--no-images`; `--no-images --save-high-res` exits with code 2; the help text mentions
      `--no-images`.

## Out of Scope

- **Making `--no-images` imply `--save-timecodes`.** It raises instead (AC4), so a run never
  silently produces nothing.
- **Deduplicating a card flagged in several back-to-back samples** (ADR 008 register 59). Without
  the extraction pass there is no batch to collapse them, so a card flagged twice gives two lines.
- **A second pass that refines the timecodes** without writing images.
- **Skipping the scan**, or reading timecodes back from an earlier run's folder.

## Technical Notes

- **No new dependency.**
- **Accuracy cost (AC3):** a scan timestamp is up to `1/fps` (0.5 s at the default 2 fps) inside
  the meme, and it is not confirmed by the full-quality re-classification, so a false positive
  that the extraction pass would have dropped still gets a line. This is the trade the user asked
  for: the best-quality download is the expensive step, and the scan timestamps are the only ones
  available without it.
- **Why `clean_method` is ignored rather than rejected (AC5):** its default is a real method, so
  `--no-images` would otherwise always collide with it. `--save-high-res` is an explicit opt-in,
  so it can be treated as a contradiction.

## Open Questions

Resolved by the user (2026-09-17):

- Q1: Does a timecodes-only run still download the best-quality copy? **No** — the whole point is
  to skip it, accepting scan-accuracy timecodes (AC2, AC3).
- Q2: A new flag, or reuse `--clean-method none`? **A new `--no-images` flag** (AC9).

## Changelog

- 2026-09-17: The user asked for an option to skip image generation. Q1–Q2 were put to the user
  and answered before drafting: skip the best-quality download entirely, behind a new
  `--no-images` flag. Drafted this spec as an iteration on
  [meme-timecodes](meme-timecodes.md) and moved it straight to `ready`, since the design questions
  it raised were the ones the user had just resolved.
- 2026-09-17: Implemented.
  - **Pipeline:** the `no_images` parameter, validated up front (AC4, AC5); with it set, `run`
    returns right after the scan, writing `timecodes.txt` from the flagged scan timestamps.
    `_write_timecodes` is now one helper used by both paths, and it prints what it wrote (AC8).
  - **CLI:** `--no-images`, with `parser.error` on `--no-images --save-high-res` (AC10).
  - **Tests:** the skip-the-best-half run (AC11), the three `ValueError` cases (AC12), the scan
    folders and the offset (AC13), the no-memes run (AC7), and the CLI wiring (AC14).
  - **Label:** the user changed the line title from `Meme` to `Мем` in the working tree during
    this change; it is now the `pipeline.MEME_LABEL` constant, used by both paths and by the
    tests. [meme-timecodes](meme-timecodes.md) AC3/AC4 are amended to match.
  - **Verified:** `extract-memes sample/short.mp4 --save-timecodes --no-images` finishes in 0.25 s,
    downloads nothing at best quality, writes only `short/timecodes.txt`, and gives the same
    `0:10` / `0:28` as the full run. `pytest -m "not slow"`: 155 passed, with the 2 pre-existing
    `test_no_arguments_prints_usage` failures (argparse colours its usage output in this
    environment) unchanged.

  All ACs are checked. Status `implemented`.
