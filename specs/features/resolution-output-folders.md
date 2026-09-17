---
title: "Low-Res and High-Res Output Folders (Iteration 3)"
status: draft
created: 2026-09-17
updated: 2026-09-17
author: ""
depends-on: ["extraction-pipeline", "heuristic-classifier", "in-memory-frames"]
---

# Low-Res and High-Res Output Folders (Iteration 3)

## Problem Statement

A run puts two kinds of meme image in one folder, `.runtime/<run-name>/saved/`:
- `thumb_frame_*.jpg`, a scan-quality copy written the moment a frame is flagged;
- `frame_*.jpg`, the best-quality copy written at the end.

Only the file-name prefix tells them apart, so taking the results means filtering out the previews.
The previews are always written, but they only existed for live feedback during Claude scans that
took hours (ADR 007 register 37). A default heuristic scan takes seconds, so most runs don't need
them. The two resolutions should live in separate folders, and low-res copies should be written
only on request. See [ADR 009](../../decisions/009-in-memory-scan-and-resolution-folders.md).

## Amends

This is an iteration spec (ADR 008, Decision 4). It applies after
[in-memory-frames](in-memory-frames.md). Once this spec is `implemented`, these acceptance criteria
read as amended here:

| Earlier spec | Criterion | Amended by |
|---|---|---|
| [extraction-pipeline](extraction-pipeline.md) | Primary user story: meme images under `.runtime/<run-name>/saved/` | User Story |
| [extraction-pipeline](extraction-pipeline.md) | AC2 step 1: create `saved/` | AC2 |
| [extraction-pipeline](extraction-pipeline.md) | AC2 step 3: always write `saved/thumb_frame_*` for a flagged frame | AC3 |
| [extraction-pipeline](extraction-pipeline.md) | AC2 steps 6–7: write and return `saved/frame_*` | AC4 |
| [extraction-pipeline](extraction-pipeline.md) | AC3: file names for the three kinds of image | AC5 |
| [extraction-pipeline](extraction-pipeline.md) | AC4: thumbnails and best-quality frames coexist in `saved/` | AC6 |
| [extraction-pipeline](extraction-pipeline.md) | AC9: the parser description names `saved/` | AC8 |
| [extraction-pipeline](extraction-pipeline.md) | AC12, AC13, AC16: test paths and thumbnail checks | AC10, AC11 |
| [heuristic-classifier](heuristic-classifier.md) | AC11: expected `<saved>/frame_…` paths | AC10 |
| [in-memory-frames](in-memory-frames.md) | AC3 step 3.3: write the thumbnail "exactly as before" | AC3 |

Not amended:
- extraction-pipeline AC5–AC8: run names, progress bars, local runs, and error propagation are
  unchanged.
- [dev-harness](dev-harness.md): AC5 only says each entry point "prints what it saved". AC9 below
  updates the printed folder.

## User Story

**Primary:**
As a user, I want the best-quality memes on their own in `.runtime/<run-name>/high-res/`, so that I
can take the results without filtering out previews.

**Secondary:**
As a user running a slow scan (for example with `--classifier claude`), I want to opt into
scan-quality copies written to `low-res/` as soon as each meme is found, so that I can check
results before the run ends.

## Acceptance Criteria

### Pipeline

- [ ] AC1: `pipeline.run` gains a trailing keyword parameter `save_low_res: bool = False`, after
      `save_frames`. All other parameters and their defaults are unchanged.
- [ ] AC2: Step 1 creates `runtime_dir/run_name/high-res/` always, and `runtime_dir/run_name/low-res/`
      only when `save_low_res` is true (parents OK, existing OK). `frames/` is created per
      in-memory-frames AC3. The pipeline never creates or writes `saved/`.
- [ ] AC3: Step 3: when a sampled frame is flagged, `run` records `(idx, ts)`. If `save_low_res` is
      true, it **immediately** writes the scan frame to `low-res/frame_<idx:06d>_<ts:.2f>s.jpg`.
      Without `save_low_res`, nothing is written for a flagged frame during the scan.
- [ ] AC4: Step 6 writes each best-quality frame to `high-res/frame_<idx:06d>_<ts:.2f>s.jpg`. Step 7
      returns those `high-res/` paths in scan order. Low-res paths are never returned.
- [ ] AC5: File names: every image uses `frame_<idx:06d>_<ts:.2f>s.jpg` with the extraction-pipeline
      AC3 rules (the scan file's index, two-decimal seconds, JPEG with `cv2.imwrite` defaults). No
      `thumb_` prefix is written anymore, so a meme's low-res and high-res copies have identical
      names. For the test video at 2 fps this gives `frames/frame_000036_1.44s.jpg`,
      `low-res/frame_000036_1.44s.jpg`, and `high-res/frame_000036_1.44s.jpg`.
- [ ] AC6: The pipeline still deletes nothing:
      - Re-running with the same run name overwrites same-named files in `high-res/` and `low-res/`
        and leaves other files in place.
      - A run without `save_low_res` leaves a `low-res/` folder from an earlier run untouched.
      - A `saved/` folder from a run made before this spec is left untouched: not read, moved, or
        migrated.
- [ ] AC7: When nothing is flagged, `run` prints `No memes found.` and returns `[]`, as before.
      `high-res/` exists and is empty, and `low-res/` exists (empty) only if `save_low_res` is
      true.

### CLI

- [ ] AC8: The CLI adds `--save-low-res` (a `store_true` flag, off by default), passed to
      `pipeline.run` as `save_low_res`. Its help text says it writes a scan-quality copy of each
      meme to `<runtime-dir>/<run-name>/low-res/` as soon as it's found. The parser description
      names `<runtime-dir>/<run-name>/high-res/` instead of `saved/`. The CLI still prints only
      the returned high-res paths.

### Dev harness

- [ ] AC9: `playground/playground.py`'s shared runner prints
      `Saved <N> memes to <PLAYGROUND_DIR>/<run_name>/high-res:` instead of naming `saved`. No
      other harness change.

### Tests

- [ ] AC10: `tests/test_pipeline.py` (skipped when `sample/short.mp4` is absent):
      - **A local run** at `fps=1.0` with a flag-every-10th fake returns paths that all live in
        `<run>/high-res/`, match `^frame_\d{6}_\d+\.\d{2}s\.jpg$`, and decode to `(144, 256)`.
        Neither `<run>/low-res/` nor `<run>/saved/` exists.
      - **The same run with `save_low_res=True`** gives the same returned paths. The names in
        `low-res/` are exactly the returned names, and each low-res file decodes to `(144, 256)`.
      - **The file-names-and-order test** checks `low-res/` names equal to the expected high-res
        names, with no prefix.
      - **The no-memes test** checks that `high-res/` exists and is empty, `low-res/` doesn't
        exist, and `download` is called only with `"worst"`.
      - **The rerun test** checks that an extra file in `high-res/` and a pre-existing
        `saved/keep-me.txt` both survive.
      - **The classifier-error test** with `save_low_res=True` checks that `low-res/` holds the
        copy of the frame flagged before the error.
      - **heuristic-classifier AC11** expects `<run>/high-res/frame_000264_10.56s.jpg` and
        `<run>/high-res/frame_000720_28.80s.jpg`.
- [ ] AC11: The real-URL test (`@pytest.mark.slow`) passes `save_low_res=True`. For every returned
      path, `low-res/<same name>` exists and its pixel height is smaller than the high-res file's.
- [ ] AC12: `tests/test_cli.py`: by default the CLI passes `save_low_res=False`, and
      `--save-low-res` passes `True`.

## Out of Scope

- **Migrating, renaming, or deleting `saved/` folders** from earlier runs.
- **A different size or format for low-res copies.** They're the scan frame exactly as decoded.
- **A scan-only mode** that skips the best-quality download and produces only low-res copies.
- **New options for `run_real_video.py`.** It prints the returned high-res paths, as before.
- **Changing `downloads/`, `frames/`, or the run-name rules.**
- **Deduplicating a card flagged in several back-to-back samples** (ADR 008 register 59).

## Technical Notes

- **No new dependency.**
- **"Low-res" and "high-res" name the download tier, not a fixed size.**
  - `low-res/` copies come from the `worst` scan download: 256x144 for the local fixtures, and
    typically 144p on YouTube.
  - `high-res/` copies come from the `best` download.
  - For a local file, both passes read the same file (video-download passthrough), so the copies
    are identical in size and pixels.
- **Why identical names:** the `thumb_` prefix existed only because both kinds shared one folder.
  With separate folders, a low-res copy and its high-res copy pair up by name.
- **Why low-res defaults to off:** the copies gave live feedback during Claude scans of 8–16 s per
  frame. The default heuristic scans `full.mp4` in seconds, so the feedback matters mainly with
  `--classifier claude`, where the user can ask for it.
- **When implemented, CLAUDE.md needs updating:**
  - Project Overview step 2 ("saved right away as scan-quality thumbnails") and step 4
    (`.runtime/<run-name>/saved/`);
  - the `.runtime/` Directory Structure (`high-res/`, and `low-res/` only with `--save-low-res`).

  See ADR 009.

## Open Questions

Resolved by the user (2026-09-17):

- Q1: Where do the two folders go? **Directly in the run folder, next to `frames/`**:
  `<run-name>/high-res/` and `<run-name>/low-res/`. `saved/` is no longer used. The rejected
  alternative was `saved/high-res/` and `saved/low-res/`.
- Q2: Are low-res copies produced by default? **No.** Only with `--save-low-res` /
  `save_low_res=True`.
- Q3: Is an ADR needed? **Yes**, [ADR 009](../../decisions/009-in-memory-scan-and-resolution-folders.md),
  shared with [in-memory-frames](in-memory-frames.md).

Open, with a proposed answer:

- [ ] Q4: Should low-res files drop the `thumb_` prefix? **Proposed: yes** (AC5). The folder already
      says what they are, and identical names pair the copies.
- [ ] Q5: Should `high-res/` be created at the start even when nothing is flagged? **Proposed: yes**
      (AC2, AC7), the same as `saved/` today. The alternative is to create it only before the first
      best-quality frame is written, so a run with no memes leaves no empty folder.

## Changelog

- 2026-09-17: The user asked for low-res and high-res memes in separate folders, with low-res memes
  produced only when an option is set.
  - The user chose `high-res/` and `low-res/` directly in the run folder (dropping `saved/`), the
    flag name `--save-low-res`, and an ADR.
  - Drafted this spec and [ADR 009](../../decisions/009-in-memory-scan-and-resolution-folders.md)
    together with [in-memory-frames](in-memory-frames.md), which it builds on.

  Status `draft`, pending review and Q4–Q5.
