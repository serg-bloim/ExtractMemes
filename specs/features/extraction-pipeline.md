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
      6. For each flagged `(idx, ts)`, numbered from 1 in scan order as `n`:
         create the batch folder `high-res/meme_<n:03d>/`; read the frames in
         `[ts - window_seconds, ts + window_seconds]` with
         `frames_from(extract_path, max(0, ts - window_seconds), count)`, where
         `count = round(2 * window_seconds * native_fps) + 1`; downscale each one to the scan
         resolution and classify it; write every frame the classifier flags to
         `meme_<n:03d>/frame_<frame_idx:06d>_<frame_ts:.2f>s.jpg` at **full quality**, and collect
         the path.
      7. Return the collected paths, batch by batch and in video order within a batch.
- [x] AC3: File-name format for all three kinds of image:
      - `idx` is the decoded frame index, zero-padded to 6 digits: the **scan file's** index for
        `frames/` and `low-res/`, and the **best file's** own index (from `frames_from`) for the
        batch frames under `high-res/meme_<n:03d>/`.
      - `ts` is seconds with exactly two decimals.
      - All images are JPEG, written with `cv2.imwrite` defaults.

      For the test video at 2 fps, this gives `frames/frame_000036_1.44s.jpg`,
      `low-res/frame_000036_1.44s.jpg`, and a batch of full-quality frames under
      `high-res/meme_001/`. Sorting names lexicographically sorts by position in the video (up to
      999,999 frames), within a batch folder.
- [x] AC17: `run` takes a trailing keyword parameter `window_seconds: float = 1.0`, the half-width
      of the batch window in AC2 step 6. The batch is clamped at the start of the video, and
      `frames_from` stops early at its end, so a meme near either end gets a shorter batch.
      Every batch folder is created even when no frame in it is flagged, so it can stay empty.
- [x] AC18: Before classifying a best-quality frame, `run` downscales it to the resolution the
      scan frames had (`cv2.INTER_AREA`), so the classifier sees the same frame size in both
      passes. A frame already at that size is passed through unchanged. The **saved** image is
      always the full-quality frame, never the downscaled one. Scan-pass frames are passed to the
      classifier unchanged, as before.
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
- [x] AC8: If `download`, `sample_frames`, `frames_from`, or the classifier raises, the exception
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
      - `high-res/` holds one `meme_<n:03d>/` folder per scan hit, numbered from 1 with no gaps;
      - the returned paths all exist, live in one of those batch folders, match
        `^frame_\d{6}_\d+\.\d{2}s\.jpg$`, decode to shape `(144, 256)`, and are exactly the files
        in the batch folders;
      - the returned paths are ordered batch by batch, and in video order within a batch;
      - the fake is called once per sample and then once per batch frame.
- [x] AC19: Batch-content test with the real default classifier (also covering
      heuristic-classifier AC11): a default run on `short.mp4` produces `meme_001/` and `meme_002/`
      holding 10 consecutive frames each, starting at `frame_000262_10.48s.jpg` and
      `frame_000716_28.64s.jpg`, and containing the two known cards `frame_000264_10.56s.jpg` and
      `frame_000720_28.80s.jpg`. (Measured: each card is on screen for exactly 10 frames, ADR 008.)
- [x] AC13: No-memes test, on `sample/short.mp4` (**not** `full.mp4`) with a never-meme fake: `run`
      returns `[]`, prints `No memes found.` (captured with `capsys`), and `download` (patched as a
      spy around the real function) is called only with `"worst"`.
- [x] AC14: Run-name tests cover every row of the AC5 table plus the `video` fallback.
- [x] AC15: CLI tests: both `--help` invocations exit 0 with output mentioning "extract". Invoking
      with no arguments exits 0 and prints usage.
- [x] AC16: One real-network test, marked `@pytest.mark.slow`: `run("https://youtu.be/AElGyY97k_0", …)`
      with **`tmp_path`** for `downloads_dir` and `runtime_dir` (never the project's own
      `downloads/`/`.runtime/`) and a fake classifier flagging every 5th call. Assert there are 6
      batch folders, the returned paths exist and sit in them, every saved frame is taller in
      pixels than the scan-quality copies in `low-res/`, and no file under `downloads_dir`
      contains `*`. It asserts rather than returning a value.

## Out of Scope

- **Refining a batch into one resulting image.** Done, in
  [batch-cleaning](batch-cleaning.md): each batch is combined into `clean/meme_<n:03d>.png`, which
  also changes what `run` returns (AC2 step 7, AC12, AC16, AC19 are amended there).
- **A CLI flag for `window_seconds`.** It's available from Python only, like `classifier_effort=None`.
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
- **Why batches instead of one frame per meme:** the scan samples at 2 fps, so it flags one frame
  of a card that is on screen for ~0.4 s (exactly 10 frames in `sample/short.mp4` and `full.mp4`,
  ADR 008). The flagged sample isn't necessarily the best of them — it can catch a transition or a
  partly drawn card. Keeping every frame of the card lets a later step choose or merge.
- **Cost of the batch pass:** it classifies `2 * window_seconds * native_fps + 1` frames per meme
  (51 at 25 fps), instead of none. That's negligible for `HeuristicClassifier` (~9 ms per frame at
  1080p) but would make `--classifier claude` roughly 50x more expensive per meme, at 8–16 s per
  frame. Worth revisiting before running a Claude scan end to end.
- **`frames_from`, not `frame_at`:** one open-and-seek per meme instead of one per frame (~10x
  faster; measurements in the frame-extraction spec).
- The batch is read by seeking the best file to the scan timestamp, so the batch frames carry the
  best file's own indices and timestamps, while `frames/` and `low-res/` names carry the scan
  file's (see frame-extraction Technical Notes on cross-file timestamps).
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

- 2026-09-17: Batch cleaning ([batch-cleaning](batch-cleaning.md),
  [ADR 010](../../decisions/010-batch-cleaning-by-trimmed-mean.md)) amends this spec: `run` gained
  `clean_method`, step 1 also creates `clean/`, each batch is combined into `clean/meme_<n:03d>.png`,
  and `run` returns those paths instead of the batch frames unless cleaning is off. "Refining a
  batch into one resulting image" is no longer out of scope.
- 2026-09-17: The user asked to process each flagged timestamp as a batch instead of a single
  frame: read the best-quality frames within ±1 s with `frames_from`, downscale each and re-check
  it with the classifier, save every match at full quality, and group the files by meme so batches
  are easy to tell apart. Refining a batch into one image is explicitly deferred.
  - Added AC17 (`window_seconds`, clamping, empty batches kept), AC18 (downscale before
    classifying, save full quality), AC19 (batch contents with the real classifier), and rewrote
    AC2 step 6–7, AC3, AC8, AC12, and AC16.
  - `pipeline.run` now uses `frames_from` and no longer calls `frame_at`; output moved from
    `high-res/frame_*.jpg` to `high-res/meme_<n:03d>/frame_*.jpg`.
  - Interpretation, flagged for review: "downscale the frame" is done **in the pipeline**, to the
    scan resolution, so it works for any classifier. `HeuristicClassifier` would have resized
    internally anyway, but `ClaudeCliClassifier` would otherwise have sent full-resolution JPEGs.
  - Verified: `run("sample/short.mp4")` gives `meme_001/` and `meme_002/` with 10 frames each,
    covering the two known cards. `pytest -m "not slow"` (98 passed) and `pytest -m slow`
    (5 passed).
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
- 2026-09-16: Ran the rebuild smoke check from ADR 007 with the real classifier:
  `extract-memes sample/short.mp4 --run-name rebuild_smoke` (defaults: 2 fps, haiku-4.5 / `low`).
  164 frames were classified in 21:57 (~8.0 s per frame) and exactly two memes were flagged and
  extracted: `frame_000264_10.56s.jpg` and `frame_000720_28.80s.jpg`. There were no false
  positives on the portrait-video look-alikes at ≈31–38 s and ≈73–76 s. `saved/` holds the two
  best-quality frames plus their two thumbnails, and `frames/` holds all 164 samples.
