---
title: "Developer Run Harness"
status: ready
created: 2026-09-16
updated: 2026-09-16
author: ""
depends-on: ["extraction-pipeline"]
---

# Developer Run Harness

## Problem Statement

A real classification run is slow (seconds per frame) and costs Claude usage. Tuning the
classifier and checking the pipeline wiring meant repeatedly running parts of the pipeline with
different settings. The combinations: a real YouTube URL or a local fixture, the real classifier or
a cheap fake, a different model or effort, fps, and a single frame. Neither `pytest` (which must
stay fast, offline, and free) nor the user-facing CLI (which has no fake classifiers) fits. The
developer built two ad-hoc tools for this, a URL runner script and an IDE playground, without a
spec. This spec records what they need to do, so they survive the rebuild.

## User Story

**Primary:**
As the developer, I want a one-command runner that pushes a real YouTube URL through the full
pipeline with either the real Claude classifier or a free fake one, so that I can check downloads
and wiring end-to-end without burning classifier usage.

**Secondary:**
As the developer, I want individually runnable playground entry points (full run, alternate
model/effort, alternate fps, full-length video, single-frame classification, progress-bar demo),
so that I can try one variation from my IDE without editing code.

## Acceptance Criteria

### `run_real_video.py` (project root)

- [ ] AC1: `python run_real_video.py [url] [options]` accepts:
      - `url` (optional, default `https://youtu.be/AElGyY97k_0`);
      - `--fps` (float, default 2.0);
      - `--mock-type {every-n,random,claude}` (default: omitted, which means the real
        `ClaudeCliClassifier`; `claude` also means real);
      - `--every-n` (int, default 5);
      - `--probability` (float, default 0.2);
      - `--run-name` (default: derived by the pipeline).
- [ ] AC2: Classifiers:
      - real: `ClaudeCliClassifier()` with its defaults;
      - `every-n`: a `FrameClassifier` fake returning `True` on calls 0, n, 2n, … (the first sampled
        frame is always flagged);
      - `random`: a fake returning `True` with probability `--probability`.

      Before running, it prints which classifier is used (for the real one, its `model` and
      `effort`), the source, and the fps.
- [ ] AC3: It calls `pipeline.run(url, downloads_dir=Path(".runtime") / "downloads", runtime_dir=Path(".runtime"), run_name=…, fps=…, classifier=…)`.
      Downloads for dev runs deliberately live under `.runtime/downloads/`, not the CLI's
      `downloads/`. Afterwards it prints `✓ Extracted N memes:` followed by the paths, or
      `No memes extracted.`.
- [ ] AC4: It imports from the installed package (`from extract_memes.classifier import …`,
      `from extract_memes.pipeline import run`), **never** `from src.extract_memes …`.

### `playground/playground.py`

- [ ] AC5: The module defines these entry points. Each writes under
      `.runtime/_playground/<run_name>/`, with downloads in `.runtime/_playground/downloads/`
      (paths resolved from the file's location, not the cwd), and prints what it saved:
      | Function | What it runs |
      |---|---|
      | `test_default_run` | `sample/short.mp4`, real classifier, default model/effort/fps, run name `default_run` |
      | `test_custom_model_and_effort` | `short.mp4`, `classifier_model="claude-sonnet-5"`, `classifier_effort="high"`, run name `custom_model_effort` |
      | `test_different_fps` | `short.mp4`, `fps=0.5`, run name `fps_0_5` |
      | `test_full_video_run` | `sample/full.mp4`, `fps=0.5`, run name `full_video` |
      | `test_classify_one_frame` | `frame_at(short.mp4, 10.56)` (a known glitch card), saved to `.runtime/_playground/single_frame.jpg`, classified with `ClaudeCliClassifier()`, prints `YES`/`NO` |
      | `test_progress_bars_demo` | `short.mp4`, `fps=2.0`, a fake flagging every 5th call with a 0.1 s sleep per call, run name `progress_bars_demo`; no Claude usage |
- [ ] AC6: The functions are named `test_*` only so IDE pytest integrations show a run icon for each
      one. The file name doesn't match pytest's `test_*.py` / `*_test.py` collection patterns, so
      running `pytest` from the project root collects nothing from `playground/` or
      `run_real_video.py`. The module docstring explains this.
- [ ] AC7: `python playground/playground.py` runs `test_progress_bars_demo()`. This replaces the
      former `playground/pb.py` wrapper, which only worked when the cwd was `playground/`.

## Out of Scope

- Automated assertions. These are manual tools; a broken or half-finished playground function
  doesn't block anything.
- Scoring the classifier against the labeled evaluation set (see meme-classifier Technical Notes).
- Exposing fake classifiers through the user-facing `extract-memes` CLI.

## Technical Notes

- No new dependencies.
- These tools read the git-ignored fixtures in `sample/` (see project-setup Technical Notes), so
  entry points that use a missing fixture simply fail.
- `test_classify_one_frame` is the fastest way to sanity-check a prompt edit. One real Claude call
  takes roughly 8–11 s.

## Open Questions

All resolved:

- Q1: Should these tools have a spec at all, given that the playground was deliberately left
  unspecced? **Yes, a light one.** The code is being erased and rebuilt, and without a spec these
  conveniences would be lost.
- Q2: `run_real_video.py` imported `src.extract_memes`, which bypasses the editable install and
  leaves a `__pycache__/` at the project root. **Import `extract_memes`** (AC4).
- Q3: Keep `playground/pb.py`? **No.** Fold it into the playground's `__main__` (AC7). Previously the
  playground's own `__main__` ran a throwaway 10-step `tqdm` loop.

## Changelog

- 2026-09-16 (commit `e5bb00e`): The developer added `playground/playground.py` with default-run,
  custom-model/effort, fps, full-video, and single-frame entry points while validating the v3
  classifier prompt.
- 2026-09-16 (commit `d90aec3`): Added `test_progress_bars_demo` (a fake classifier with sleeps) and
  `playground/pb.py` to see the new progress bars without Claude usage.
- 2026-09-16 (commit `95fc3a4`): Added `run_real_video.py`, a URL runner with `every-n`/`random` fake
  classifiers, plus `tests/test_with_real_video.py`.
- 2026-09-16 (commit `f0521ea`): `run_real_video.py` now defaults to the real Claude classifier
  (`--mock-type` omitted or `claude`) and downloads into `.runtime/downloads/`.
- 2026-09-16: Documentation consolidation for the planned rebuild
  ([ADR 007](../../decisions/007-documentation-consolidation-for-rebuild.md)). Wrote this spec
  retroactively from the existing scripts, and fixed the `src.` import and the `pb.py` cwd
  dependency. Status `ready`.
