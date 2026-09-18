---
title: "Meme Timecodes File"
status: implemented
created: 2026-09-17
updated: 2026-09-17
author: ""
depends-on: ["extraction-pipeline", "batch-cleaning"]
---

# Meme Timecodes File

## Problem Statement

A run produces one image per meme, but nothing says *where* in the source video each meme is. The
timestamps only survive in the names of the per-frame files under `high-res/meme_<n>/`, which are
written only with `--save-high-res` and are in seconds-with-decimals, not a form that can be pasted
anywhere. A user who wants to annotate the source video — YouTube chapters in the description, or
just a list of jump points — has to reconstruct the times by hand.

## User Story

**Primary:**
As a user, I want a text file listing the start timecode of every meme found, one per line in
YouTube's timecode format, so that I can paste it into a video description or use it to jump
straight to each meme.

**Secondary:**
As a user, I want to shift every timecode by a fixed offset (for example one second earlier), so
that a link or chapter starts just before the meme appears rather than exactly on it.

## Acceptance Criteria

### Pipeline

- [x] AC1: `pipeline.run` gains two trailing keyword parameters, `save_timecodes: bool = False` and
      `timecode_offset: float = 0.0`. All other parameters and their defaults are unchanged.
- [x] AC2: A meme's start time is the **smallest timestamp among the best-quality frames the
      classifier accepted for that meme** (the batch frames), not the flagged scan timestamp.
- [x] AC3: With `save_timecodes=True`, `run` writes `<runtime_dir>/<run_name>/timecodes.txt` after
      extraction, containing one line per meme that produced at least one accepted frame, in meme
      order: `<timecode> Мем <n>`, where `<n>` is the same 1-based meme number used for
      `clean/meme_<n:03d>.png` and `high-res/meme_<n:03d>/` (unpadded in the line, e.g. `Мем 7`). The label is `pipeline.MEME_LABEL`, `Мем`.
      The file ends with a newline and is written with UTF-8 encoding.
- [x] AC4: A timecode is the start time in whole seconds (truncated), formatted `M:SS` — with no
      leading zero on the minutes — and `H:MM:SS` once the time reaches one hour. Examples:
      `0:00`, `0:07`, `12:05`, `1:00:00`, `2:03:09`.
- [x] AC5: `timecode_offset` is added to every start time before formatting. It may be negative
      (`-1.0` puts each timecode one second earlier); the result is clamped at `0.0`, never
      negative. The default, `0.0`, leaves the start times unchanged.
- [x] AC6: Without `save_timecodes`, no `timecodes.txt` is written, and an existing one from an
      earlier run is left untouched. With `save_timecodes`, the file is overwritten.
- [x] AC7: When nothing is flagged, `run` prints `No memes found.` and returns `[]` as before, and
      writes no `timecodes.txt` even with `save_timecodes=True`.
- [x] AC8: The returned value is unchanged: `timecodes.txt` is never added to the returned paths.

### CLI

- [x] AC9: The CLI adds `--save-timecodes` (a `store_true` flag, off by default), passed as
      `save_timecodes`, whose help text names `<runtime-dir>/<run-name>/timecodes.txt`.
- [x] AC10: The CLI adds `--timecode-offset SECONDS` (float, default `0.0`), passed as
      `timecode_offset`, whose help text says a negative value shifts the timecodes earlier.

### Tests

- [x] AC11: `tests/test_pipeline.py`: a local run with `save_timecodes=True` writes
      `timecodes.txt` with one line per returned meme, each matching
      `^(\d+:)?\d?\d:\d\d <label> \d+$`, numbered `Мем 1 … Мем N` in order, and with
      non-decreasing times. A run without the flag writes no such file, and leaves an existing one
      untouched. The no-memes run writes none.
- [x] AC12: `tests/test_pipeline.py`: a run with `timecode_offset=-1.0` gives times exactly one
      second earlier than the same run without an offset, except where that would go below zero,
      where the timecode is `0:00`.
- [x] AC13: The timecode formatter is unit-tested at the boundaries: `0.0` → `0:00`, `7.9` →
      `0:07`, `59.999` → `0:59`, `60.0` → `1:00`, `725.0` → `12:05`, `3599.0` → `59:59`, `3600.0` →
      `1:00:00`, `7389.0` → `2:03:09`.
- [x] AC14: `tests/test_cli.py`: by default the CLI passes `save_timecodes=False` and
      `timecode_offset=0.0`; `--save-timecodes` passes `True`; `--timecode-offset -1.5` passes
      `-1.5`; a non-numeric offset exits with code 2.

## Out of Scope

- **Chapter titles beyond the `Мем <n>` label.** Naming what a meme actually is would need a captioning
  pass.
- **A `0:00 Intro` first line.** YouTube requires chapters to start at `0:00`; adding a synthetic
  first chapter is the user's job when pasting.
- **End timecodes, durations, or any other format** (WebVTT, CSV, JSON).
- **Writing timecodes for a scan-only run** — the file is produced after extraction, because the
  start time comes from the best-quality batch (AC2).
- **Deduplicating a card flagged in several back-to-back samples** (ADR 008 register 59): the same
  card flagged twice still produces two memes and therefore two lines.

## Technical Notes

- **No new dependency.**
- **Why the batch minimum and not the flagged timestamp (AC2):** the scan samples at ~2 fps, so a
  flagged frame sits up to half a second inside the meme. The extraction pass already
  re-classifies every full-quality frame in a ±`window_seconds` window around it, and the earliest
  frame it accepts is the closest thing the pipeline knows to the meme's first frame.
- **Format (AC4):** YouTube parses chapter timestamps as `M:SS` / `H:MM:SS`, and requires a title
  after the timestamp, which is why the line carries `<label> <n>`. Truncating rather than rounding
  keeps a timecode from landing after the meme starts.

## Open Questions

Resolved by the user (2026-09-17):

- Q1: Which timestamp is "the start of a meme"? **The earliest accepted batch frame** (AC2), plus
  an offset option; no offset by default.
- Q2: What does a line look like? **`0:07 Meme 1`** — YouTube's chapter format (AC3, AC4).
- Q3: Is the file always written? **No** — only with `--save-timecodes`, to
  `<run-name>/timecodes.txt` (AC9).

## Changelog

- 2026-09-17: The user asked for an option producing a text file with the start timecode of each
  meme, one per line, in YouTube timecode format. Q1–Q3 were put to the user and answered before
  drafting (see Open Questions); the answers also added the offset option (AC5, AC10). Drafted
  this spec and moved it straight to `ready`, since the design questions it raised were the ones
  the user had just resolved.
- 2026-09-17: Implemented.
  - **Pipeline:** `format_timecode` (module-level, so it can be unit-tested), plus the
    `save_timecodes` and `timecode_offset` parameters. The extraction loop records the first
    accepted frame's timestamp per meme and, at the end, writes `timecodes.txt` when asked.
  - **CLI:** `--save-timecodes` and `--timecode-offset SECONDS`.
  - **Tests:** the formatter's boundaries (AC13), one line per meme with ordered times, no file
    without the flag and an existing file left alone (AC11), the `-1.0` offset shifting every line
    (AC12), the no-memes run writing nothing (AC7), and the CLI wiring and help text (AC14).
  - **Verified:** `extract-memes sample/short.mp4 --save-timecodes` writes `0:10 Мем 1` /
    `0:28 Мем 2`, and `--timecode-offset -1` writes `0:09` / `0:27`.
    `pytest -m "not slow"`: 149 passed, with the 2 pre-existing `test_no_arguments_prints_usage`
    failures (argparse colours its usage output in this environment) unchanged from `HEAD`.

  All ACs are checked. Status `implemented`.
- 2026-09-17: The user changed the line's title from `Meme` to `Мем` in the working tree. Made it
  the `pipeline.MEME_LABEL` constant and amended AC3, AC4, AC11 and the Technical notes to name
  the label rather than the English word — see [no-images](no-images.md), which added a second
  place that writes these lines.
