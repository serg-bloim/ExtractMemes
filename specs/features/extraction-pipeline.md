---
title: "Extraction Pipeline + CLI"
status: implemented
created: 2026-09-16
updated: 2026-09-16
author: ""
depends-on: ["video-download", "frame-extraction", "meme-classifier"]
---

# Extraction Pipeline + CLI

## Problem Statement

`downloader.py`, `frame_extractor.py`, and `classifier.py` each do one piece of the job. Something
has to orchestrate them into the flow from
[ADR 004](../../decisions/004-claude-classifier-and-dual-resolution-download.md), laid out as
[ADR 005](../../decisions/005-runtime-layout-and-classifier-checkpoint.md) describes: scan a
worst-quality copy for meme timecodes, then pull those frames from a best-quality copy. Every
intermediate frame is kept for inspection. A scan with the real classifier takes minutes to hours,
so the user also needs live progress, and needs to see discovered memes as soon as they're found.
All of this must run from one command.

## User Story

**Primary:**
As a user, I want to run `extract-memes <youtube-url-or-local-path>` and get meme images under
`.runtime/<run-name>/saved/`, so that one command gives me the whole pipeline's result.

**Secondary:**
As a user watching a long scan, I want a progress bar and discovered memes written immediately,
so that I can check results (and stop early) without waiting for the whole run.

## Acceptance Criteria

### Library: `pipeline.run`

- [x] AC1: `src/extract_memes/pipeline.py` exposes
      `run(source: str, downloads_dir: Path = Path("downloads"), runtime_dir: Path = Path(".runtime"), run_name: str | None = None, fps: float = 2.0, classifier: FrameClassifier | None = None, classifier_model: str = "claude-haiku-4-5-20251001", classifier_effort: str | None = "low") -> list[Path]`.
      If `classifier` is `None`, a `ClaudeCliClassifier(model=classifier_model, effort=classifier_effort)`
      is built inside `run`. Otherwise `classifier_model`/`classifier_effort` are ignored. Tests
      inject fakes without needing `claude` installed.
- [x] AC2: `run` executes these steps in this order:
      1. Resolve `run_name` (AC5). Create `runtime_dir/run_name/frames/` and
         `runtime_dir/run_name/saved/` (parents OK, existing OK).
      2. `scan_path = download(source, "worst", downloads_dir)`.
      3. For each `(idx, ts, frame)` in `sample_frames(scan_path, fps=fps)`:
         write `frames/frame_<idx:06d>_<ts:.2f>s.jpg`;
         call `classifier.is_meme()` on **that written file**;
         if it's a meme, record `(idx, ts)` and **immediately** write the same frame to
         `saved/thumb_frame_<idx:06d>_<ts:.2f>s.jpg`.
      4. If nothing was flagged, print `No memes found.` to stdout and return `[]`. Don't do the
         best-quality download.
      5. `extract_path = download(source, "best", downloads_dir)`.
      6. For each flagged `(idx, ts)` in scan order:
         `frame_at(extract_path, ts)`, write `saved/frame_<idx:06d>_<ts:.2f>s.jpg`, collect the
         path.
      7. Return the collected best-quality paths in scan order. Thumbnails aren't included.
- [x] AC3: File-name format for all three kinds of image:
      - `idx` is the **scan file's** decoded frame index, zero-padded to 6 digits.
      - `ts` is seconds with exactly two decimals.
      - All images are JPEG, written with `cv2.imwrite` defaults.

      For the test video at 2 fps, this gives `frames/frame_000036_1.44s.jpg`,
      `saved/thumb_frame_000036_1.44s.jpg`, and `saved/frame_000036_1.44s.jpg`. Sorting names
      lexicographically sorts by position in the video (up to 999,999 frames).
- [x] AC4: Nothing the pipeline writes is ever deleted by it:
      - `frames/` keeps every sampled frame.
      - `thumb_frame_*` (scan quality) and `frame_*` (best quality) for the same timestamp coexist
        in `saved/`, without being reconciled.
      - Re-running with the same run name overwrites same-named files and leaves other files in
        place.
- [x] AC5: The default run name comes from `source` and is then slugified: replace every run of
      `[^A-Za-z0-9_-]` with `_`, strip `_` from both ends, and fall back to `video` if nothing is
      left. The base name before slugifying:
      - Local path (no `://`): the file stem.
      - URL with a `v` query parameter (`youtube.com/watch?v=<id>`): that value.
      - Other URLs: the last path segment (`youtu.be/<id>`, `youtube.com/shorts/<id>`), or the host
        if the path is empty.

      | source | run name |
      |---|---|
      | `sample/short.mp4` | `short` |
      | `https://youtu.be/AElGyY97k_0` | `AElGyY97k_0` |
      | `https://www.youtube.com/watch?v=dQw4w9WgXcQ` | `dQw4w9WgXcQ` |
      | `https://www.youtube.com/shorts/abc123` | `abc123` |
- [x] AC6: Progress is shown with `tqdm`: `desc="Scanning frames"` wraps the sampled-frame iteration
      in step 3, and `desc="Extracting memes"` wraps the flagged list in step 6.
- [x] AC7: When `source` is a local file, the whole run makes no network access and uses that one
      file for both passes (per the video-download spec's passthrough).
- [x] AC8: If `download`, `sample_frames`, `frame_at`, or `classifier.is_meme` raises, the exception
      propagates and aborts the run. There's no silent skipping. Files already written (frames,
      thumbnails) stay on disk.

### CLI: `extract-memes` / `python -m extract_memes`

- [x] AC9: `src/extract_memes/__main__.py` builds an `argparse` parser (`prog="extract-memes"`, a
      description of the tool's purpose) with:
      - an **optional** positional `source` (`nargs="?"`), a YouTube URL or local video path;
      - `--fps` (float, default 2.0);
      - `--downloads-dir` (Path, default `downloads`);
      - `--runtime-dir` (Path, default `.runtime`);
      - `--run-name` (default: derived per AC5);
      - `--classifier-model` (default `claude-haiku-4-5-20251001`);
      - `--classifier-effort` (choices `low|medium|high|xhigh|max`, default `low`).

      `main()` passes them to `pipeline.run`. The console script `extract-memes` maps to
      `extract_memes.__main__:main`.
- [x] AC10: With no `source`, the CLI prints the help text and exits 0 without running anything.
      With a `source`, it runs the pipeline and prints each returned path on its own line (nothing
      extra when there are no memes; `run` already printed `No memes found.`).
- [x] AC11: `extract-memes --help` and `python -m extract_memes --help` exit 0 with no network
      access and no ffmpeg setup (no import-time side effects; see video-download AC6).

### Tests

- [x] AC12: Offline integration test (module skipped if `sample/short.mp4` is absent). Run on
      `short.mp4` with `fps=1.0`, `tmp_path` dirs, and a fake classifier that returns `True` on
      every 10th call. Assert:
      - the returned paths are non-empty, all exist, live in `tmp_path/.runtime/short/saved/`,
        match `^frame_\d{6}_\d+\.\d{2}s\.jpg$`, and decode to shape `(144, 256)`;
      - `frames/` holds exactly one `.jpg` per classifier call;
      - `saved/` holds exactly as many `thumb_frame_*.jpg` files as there are returned paths.
- [x] AC13: No-memes test, on `sample/short.mp4` (**not** `full.mp4`) with a never-meme fake: `run`
      returns `[]`, prints `No memes found.` (captured with `capsys`), and `download` (patched as a
      spy around the real function) is called only with `"worst"`.
- [x] AC14: Run-name tests cover every row of the AC5 table plus the `video` fallback.
- [x] AC15: CLI tests: both `--help` invocations exit 0 with output mentioning "extract". Invoking
      with no arguments exits 0 and prints usage.
- [x] AC16: One real-network test, marked `@pytest.mark.slow`: `run("https://youtu.be/AElGyY97k_0", …)`
      with **`tmp_path`** for `downloads_dir` and `runtime_dir` (never the project's own
      `downloads/`/`.runtime/`) and a fake classifier flagging every 5th call. Assert the returned
      paths exist, the best-quality frames are larger than the thumbnails in pixel height, and no
      file under `downloads_dir` contains `*`. It asserts rather than returning a value.

## Out of Scope

- Deduplicating a meme that appears in several consecutive samples (ADR 002 M7, still deferred).
  With the v3 prompt at 2 fps, each glitch card in `short.mp4` was flagged once, but that isn't
  guaranteed.
- Cleaning up `downloads/` or `.runtime/`, during or across runs.
- Resuming an interrupted run, or skipping frames that were already classified.
- Concurrency: scanning and classification are sequential, and the best-quality download starts
  only after the full scan.
- A `total` on the scan progress bar. `sample_frames` is a generator and `CAP_PROP_FRAME_COUNT` is
  unreliable, so the bar shows count and rate, not percent or ETA. It could be improved later as
  an estimate.
- A CLI way to omit `--effort` entirely (`classifier_effort=None` is available from Python only).

## Technical Notes

- **Runtime dependency introduced by this spec:** `tqdm` (known-good 4.70.1).
- All default paths (`downloads`, `.runtime`) are **relative to the current working directory**,
  not the project root. Run the CLI from the project root to keep artifacts inside the project.
- The best-quality frame is chosen by seeking to the scan timestamp. The file name keeps the scan
  file's index even though it's taken from the best file (see frame-extraction Technical Notes).
- The classifier gets the JPEG written to `frames/`, so it sees a JPEG-compressed, scan-quality
  frame (typically 256x144).
- `run` prints `No memes found.` itself. The library does this intentionally; the CLI adds nothing
  in that case.
- Runtime expectations with the real classifier: see meme-classifier Technical Notes. Roughly
  8–11 s per sampled frame, so ~43 min for the 78.56 s `short.mp4` at 2 fps.
- Expected real-run result on `sample/short.mp4` with defaults: two memes, at `10.56s` and
  `28.80s`. Treat it as a smoke check, not an exact assertion: the classifier isn't
  deterministic.

## Open Questions

All resolved:

- Q1: Where do run artifacts go? **`.runtime/<run-name>/{frames,saved}/`** inside the project, with
  frames kept (ADR 005). Not `/tmp`, and not `output/`.
- Q2: PNG or JPEG output? **JPEG everywhere** (`frames/`, thumbnails, final frames). Changed in commit
  `78149cc` ("png -> jpg"). The reason wasn't written down; the practical effect is one consistent
  format and smaller files.
- Q3: Should thumbnails be replaced by or reconciled with the final frames? **No.** They coexist
  permanently. They exist for immediate feedback during long scans.
- Q4: Must `source` be given? **No.** It's an optional positional: with no argument the CLI prints
  help and exits 0. (The earlier spec text said "required positional", but the implementation and
  its tests always used `nargs="?"`.)
- Q5: `watch?v=` URLs all got the run name `watch`, so different videos collided in one folder.
  **Use the `v` query parameter** (AC5). This defect was found during consolidation.
- Q6: Where should downloads go by default? **`downloads/`** for the CLI and `pipeline.run`. The
  dev runner `run_real_video.py` deliberately uses `.runtime/downloads/` (see the dev-harness spec).
  Changing the CLI default is a separate decision.
- Q7: The no-memes test scanned the ~1-hour `sample/full.mp4` (7842 JPEG writes, and no skip guard
  for that file). **Use `short.mp4`** (AC13).

## Changelog

- 2026-09-16: Implemented as the final piece of "implement the whole project," wiring
  `downloader`, `frame_extractor`, and `classifier` into `pipeline.run` and extending the CLI.
  Validated end-to-end against `sample/short.mp4` with the real `ClaudeCliClassifier`.
- 2026-09-16: The user reviewed that first run's output (a presenter-with-inset frame, not a real
  meme) and asked for: all artifacts kept inside the project dir under `.runtime/<run>/`, scan
  frames no longer deleted, and a 2fps default (see
  [ADR 005](../../decisions/005-runtime-layout-and-classifier-checkpoint.md)). Replaced
  `output_dir` with `runtime_dir`/`run_name` producing `frames/` + `saved/`, bumped the default
  `fps` to 2.0, and updated the integration test to check both directories.
- 2026-09-16: The user asked how to configure the classifier's model/effort; neither was exposed
  outside constructing `ClaudeCliClassifier` directly in Python. Added `classifier_model` /
  `classifier_effort` params to `pipeline.run` and `--classifier-model` / `--classifier-effort`
  CLI flags (see the meme-classifier spec for the underlying `--effort` flag).
- 2026-09-16: The user asked for a progress bar showing frame-by-frame processing status. Added
  `tqdm` as a dependency and wrapped both the scan pass ("Scanning frames") and the extraction pass
  ("Extracting memes") in progress bars. Also fixed a pre-existing test bug where the frame glob
  pattern looked for `.png` but the pipeline saves `.jpg`.
- 2026-09-16: Added immediate thumbnail saves during the scan pass. When a frame is flagged
  as a meme, it's written right away to `saved/thumb_frame_<ts>s.jpg` (worst-quality preview
  from the scan video), for real-time feedback. The extraction pass later writes the
  best-quality files. Both files stay in `saved/` permanently.
- 2026-09-16: The user asked for frame indices in file names, for easier sorting and reference.
  Extended `sample_frames` to yield actual video frame indices, then added zero-padded frame
  numbers to all file names in `frames/` and `saved/` (e.g. `frame_000042_1.25s.jpg`,
  `thumb_frame_000127_2.15s.jpg`).
- 2026-09-16 (commit `78149cc`): Changed the extracted meme format from `.png` to `.jpg`. The spec's
  AC1, AC10, and Technical Notes still said `.png` afterwards (drift).
- 2026-09-16 (commit `f4bfdf8`, undocumented at the time): The pipeline started calling
  `download(source, "wv*", …)` / `download(source, "bv*", …)` to work around unavailable YouTube
  formats. See [ADR 006](../../decisions/006-youtube-video-only-formats-and-download-toolchain.md).
- 2026-09-16 (commit `95fc3a4`, undocumented at the time): Added `tests/test_with_real_video.py`,
  which ran the pipeline on a real URL without a `slow` marker, wrote into the project's own
  `downloads/` and `.runtime/`, and returned a value from the test.
- 2026-09-16: Documentation consolidation for the planned rebuild
  ([ADR 007](../../decisions/007-documentation-consolidation-for-rebuild.md)). Fixed spec drift:
  JPEG everywhere, file names with a 6-digit index for all three image kinds, optional `source`
  that prints help, and `worst`/`best` quality names instead of selectors. Spelled out the exact
  step order, including skipping the best-quality download when nothing is flagged (AC2).
  Documented error propagation (AC8). Fixed defects found during review: run names for `watch?v=`
  URLs (AC5), the no-memes test scanning `full.mp4` (AC13), and the real-URL test polluting the
  project and lacking a `slow` marker (AC16). Renumbered ACs into Library / CLI / Tests groups.
  Reset status to `ready` with unchecked ACs because the implementation will be erased and rebuilt.
- 2026-09-16: "Implement the project according to the docs in it. Commit each feature
  individually." Rebuild step 5 of [ADR 007](../../decisions/007-documentation-consolidation-for-rebuild.md).
  Added `src/extract_memes/pipeline.py`: `default_run_name` (AC5) and `run`, which follows the
  AC2 steps in order with `tqdm` bars. A failed `cv2.imwrite` raises `RuntimeError` instead of
  being ignored, so no image is silently skipped (AC8). Replaced the skeleton
  `__main__.py` with the full parser (AC9) and `main(argv=None)`, which prints help for no
  `source` and otherwise prints each returned path. Declared `tqdm`. Added
  `tests/test_pipeline.py`: AC12–AC14 and AC16, plus the default-classifier wiring (AC1), file
  names and scan order (AC3), the progress-bar descriptions (AC6), overwrite-on-rerun (AC4), a
  local run with yt-dlp and ffmpeg setup patched to fail (AC7), and error propagation (AC8).
  Rewrote `tests/test_cli.py` for AC15, the argument pass-through, and help leaving the cwd
  untouched (AC11). Verified: `pytest -m "not slow"` (60 passed, also with no `claude` or `node`
  on `PATH`) and `pytest -m slow` (4 passed). All ACs checked; status `implemented`.
