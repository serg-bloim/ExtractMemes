---
title: "Frame Extraction"
status: implemented
created: 2026-09-16
updated: 2026-09-16
author: ""
depends-on: ["project-setup"]
---

# Frame Extraction

## Problem Statement

The pipeline reads frames out of a video file in two ways. First, a cheap, regular sampling pass
over the whole low-res video finds candidate meme timecodes. Then, once a timecode is known to
contain a meme, a precise single-frame read gets that frame from the high-res video. Both reads
have to work without a system `ffmpeg` install and must report positions (frame index and
timestamp) that later stages can use in file names and seeks.

## User Story

**Primary:**
As the ExtractMemes pipeline, I want to sample frames from a video at a roughly fixed rate, with
each frame's index and timestamp, so that I can hand each sampled frame to the classifier without
classifying every decoded frame.

**Secondary:**
As the ExtractMemes pipeline, I want to read the frame at an exact timestamp from a (different,
higher-quality) copy of the same video, so that I can save the full-quality meme image once its
timecode is known.

**Secondary:**
As the developer, I want to read a run of consecutive frames starting at a known timestamp, so that
I can study every frame a meme is on screen for without paying the open-and-seek cost per frame.

## Acceptance Criteria

- [x] AC1: `src/extract_memes/frame_extractor.py` exposes
      `sample_frames(video_path: Path, fps: float = 2.0) -> Iterator[tuple[int, float, np.ndarray]]`,
      which yields `(frame_index, timestamp_seconds, frame)`. `frame_index` is the 0-based index of
      the decoded frame in the source file (not a sample counter). `timestamp_seconds` is the
      frame's own presentation time, `cap.get(cv2.CAP_PROP_POS_MSEC) / 1000` read right after the
      frame, not `frame_index / native_fps`: a file can have uneven frame spacing, so its nominal
      rate drifts from real time. Items come in strictly increasing order.
- [x] AC2: Sampling step: `native_fps = cap.get(cv2.CAP_PROP_FPS) or fps`,
      `step = max(1, round(native_fps / fps))` using Python's built-in `round` (half-to-even).
      Every `step`-th decoded frame is yielded, starting at index 0. So the effective rate is
      `native_fps / step`, which isn't always exactly `fps`. For a 25 fps source at the default
      `fps=2.0`: `round(12.5) == 12`, giving 2.083 samples/s at `0.00s, 0.48s, 0.96s, …`. This is
      the documented, intended behavior (see Open Questions Q3).
- [x] AC3: `sample_frames` decodes sequentially with `cap.read()` and never seeks per sample. It
      doesn't use `cv2.CAP_PROP_FRAME_COUNT` to decide how many frames to read (that property is
      unreliable, see Technical Notes). It stops at the first failed read.
- [x] AC4: It also exposes `frame_at(video_path: Path, timestamp_seconds: float) -> np.ndarray`.
      This seeks with `cap.set(cv2.CAP_PROP_POS_MSEC, timestamp_seconds * 1000)` and reads one
      frame. If no frame can be read, it raises `RuntimeError` naming both the timestamp and the
      path.
- [x] AC5: Both functions use `cv2.VideoCapture` (OpenCV's bundled FFmpeg backend). No system
      `ffmpeg`/`ffprobe` binary is required.
- [x] AC6: If the video can't be opened (`not cap.isOpened()`: missing file, unsupported codec),
      both functions raise `RuntimeError("Could not open video file: <path>")`. `sample_frames` is a
      generator, so it raises on the first `next()`, not when it's called.
      **Amended by [fail-on-undecodable-video](fail-on-undecodable-video.md) AC1:** `sample_frames` also
      raises `RuntimeError` when the file opens but its first read fails.
- [x] AC7: The `VideoCapture` is always released (`try/finally`), including when the consumer stops
      iterating early or an exception propagates.
- [x] AC8: Frames are returned exactly as decoded: BGR `numpy.ndarray` at the file's native
      resolution, with no resizing or color conversion. That's what `cv2.imwrite` expects.
- [x] AC9: Unit tests run against `sample/short.mp4` (module skipped if that fixture is absent) and
      check:
      at `fps=1.0`, 79 frames, all within the range 70–85;
      at the default `fps=2.0`, exactly 164 frames with `frame_index` values `0, 12, 24, …`;
      timestamps strictly increasing;
      every frame is `(144, 256)`;
      `frame_at(short.mp4, 10.0)` has shape `(144, 256)`;
      for several indices `i` (e.g. 0, 12, 150, 288), `frame_at(short.mp4, i / 25)` is
      pixel-identical to the `i`-th sequentially decoded frame;
      and a missing file raises `RuntimeError` on iteration.
- [x] AC10: It also exposes
      `frames_from(video_path: Path, start_seconds: float, count: int) -> Iterator[tuple[int, float, np.ndarray]]`,
      which yields up to `count` consecutive frames starting at the frame at `start_seconds`:
      - it opens the file and seeks **once** (`CAP_PROP_POS_MSEC`), then reads sequentially, so
        every frame after the first costs one decode;
      - `frame_index` is read from `CAP_PROP_POS_FRAMES` before each read, because the seek lands
        on the nearest decodable frame, which can be earlier than `start_seconds`;
      - `timestamp_seconds` is `frame_index / native_fps` (as in AC1), falling back to
        `CAP_PROP_POS_MSEC` when the file reports `fps == 0`. `CAP_PROP_POS_MSEC` is not used
        otherwise: it can lag `CAP_PROP_POS_FRAMES` by one frame (see Technical Notes);
      - it stops early at the first failed read, so it yields fewer than `count` frames near the
        end of the file, and nothing at all when `start_seconds` is past the end. That is not an
        error (unlike AC4's `frame_at`);
      - AC5–AC8 apply to it as well: OpenCV only, `RuntimeError` on an unopenable file (raised on
        the first `next()`), release in `try/finally`, frames exactly as decoded.
- [x] AC11: Unit tests for `frames_from` against `sample/short.mp4`, plus fixture-free mocked ones:
      5 frames from `10.56s` have indices `264…268` and timestamps `10.56…10.72`, shape
      `(144, 256)`, and are pixel-identical to the same sequentially decoded frames;
      `frames_from(short.mp4, 78.40, 10)` yields only the 4 frames left in the file;
      `frames_from(short.mp4, 3600.0, 5)` yields nothing;
      a missing file raises `RuntimeError` on the first `next()`;
      and with a mocked `VideoCapture`, stopping early releases the capture, `VideoCapture` was
      constructed once, and `set` was called once with `CAP_PROP_POS_MSEC`.

## Out of Scope

- Frame preprocessing (resizing, cropping, color correction).
- Perceptual-hash deduplication (ADR 002 M7, still deferred).
- Parallel or async decoding, and hardware acceleration.
- Snapping to keyframes, or frame-accurate cuts beyond what `CAP_PROP_POS_MSEC` gives.

## Technical Notes

- **Runtime dependencies introduced by this spec:** `opencv-python-headless` (known-good 5.0.0.93)
  and `numpy` (known-good 2.5.3; imported directly for type hints, so declare it explicitly rather
  than relying on OpenCV to pull it in). The headless build is used instead of the
  `opencv-python` named in ADR 002, because nothing is ever displayed and it avoids GUI/Qt
  libraries. The `cv2` API is the same.
- **Seek accuracy (verified 2026-09-16):** `frame_at(path, i / fps)` returned the pixel-identical
  `i`-th frame for H.264 `sample/short.mp4` (256x144) and for the VP9 best-quality download of the
  test video (640x360). One apparent mismatch in `sample/short2.mp4` (index 288 matched 287) was
  two identical consecutive frames (pixel diff 0.0). So no keyframe-snapping workaround is needed
  with this OpenCV build.
- **`CAP_PROP_FRAME_COUNT` is unreliable:** `sample/short2.mp4` reports 1611 frames but decodes only
  1501. Use it for progress estimates at most, never for correctness.
- **Cross-file timestamps:** the pipeline computes timestamps on the *scan* (worst) file and seeks
  the *extraction* (best) file by time. Both tiers of the test video are 25 fps, so indices line up.
  If the tiers ever have different frame rates, seeking by time is still correct, but the scan
  file's `frame_index` in file names won't match the best file's frame numbering.
- **Why `frames_from` exists (measured 2026-09-17** on the 1080p VP9 download of
  `0TSqnhLXYfA`, 10 consecutive frames at each of 4 timestamps): `frame_at` per frame took 3.92 s
  (~98 ms each), because each call reopens the file and decodes forward from the preceding
  keyframe. Opening and seeking once per run of frames took 0.41 s. Reusing one capture across all
  four runs took 0.27 s; that was rejected as not worth the lifetime management (user decision,
  2026-09-17). Keyframes in that file are ~2.5 s apart, which is why a seek is expensive and the
  frames after it are not (~10 ms each).
- **`CAP_PROP_POS_MSEC` can lag `CAP_PROP_POS_FRAMES` by one frame** (observed 2026-09-17 on
  `sample/short.mp4`, H.264 25 fps): right after a seek to `10.56s`, `POS_FRAMES` reported 264 and
  `POS_MSEC` reported `10.52s`, while the frame then read was pixel-identical to sequentially
  decoded frame 264. So `frames_from` derives the timestamp from the index (AC10).
- **Sample counts for reference** (at `fps=2.0`, step 12):
  - `sample/short.mp4` (1964 frames): 164 samples.
  - `sample/full.mp4` (94095 frames): 7842 samples.
  - Test video `AElGyY97k_0` (302 frames): 26 samples.

## Open Questions

All resolved:

- Q1: Sequential decode or seek per sample? **Sequential** `cap.read()` for the dense sampling pass,
  which is more reliable across codecs. **Seek** only for the single-frame read.
- Q2: Should `sample_frames` report the frame index as well as the timestamp? **Yes**, so file names
  can include the real frame number (user request, see Changelog).
- Q3: The effective rate differs from the requested one (`round(12.5) == 12` gives 2.083 fps
  instead of 2.0). Fix it? **No, keep it and document it.** Every existing run artifact and note
  uses these sample points (e.g. the known meme at `10.56s` = frame 264 = 22 × 12). Other step or
  rounding choices would silently change which frames get scanned. Revisit only as a deliberate
  spec change.
- Q4: What if the video reports `fps == 0`? **Fall back to the requested `fps`** (step 1: every
  decoded frame is sampled, with timestamps based on the requested rate). `frames_from` has no
  requested rate, so it falls back to `CAP_PROP_POS_MSEC` instead (AC10).
- Q5: Should `frames_from` reuse one capture across several runs of frames, for another ~1.5x?
  **No** (user decision, 2026-09-17). Each call opens and releases its own capture, so it stays a
  plain generator with no lifetime to manage and no ordering requirement between calls. The
  measurements are in Technical Notes.
- Q6: Should `frames_from` raise when `start_seconds` is past the end, as `frame_at` does?
  **No.** It yields nothing, like `sample_frames` stopping at the first failed read. A caller
  asking for a run of frames can't know how many are left near the end of the file.

## Changelog

- 2026-09-16: Implemented alongside the rest of the pipeline for the "implement the whole
  project" request. Added `frame_at` (not in ADR 002's original M2 scope) because ADR 004's
  two-pass design needs an exact-timecode read from the high-res download, not just fixed-rate
  sampling. Verified against `sample/short.mp4` (78.56s, 25fps, 256x144).
- 2026-09-16: Bumped the default scan rate from 1fps to 2fps per the checkpoint in
  [ADR 005](../../decisions/005-runtime-layout-and-classifier-checkpoint.md).
- 2026-09-16: Updated `sample_frames` to also yield the actual video frame index (not just the
  timestamp), so file names can include frame numbers for easier reference and sorting.
- 2026-09-16: Documentation consolidation for the planned rebuild
  ([ADR 007](../../decisions/007-documentation-consolidation-for-rebuild.md)). Made the exact step
  formula and its half-to-even rounding explicit (AC2, Q3). Recorded that `CAP_PROP_FRAME_COUNT` is
  unreliable and that seek accuracy was verified on H.264 and VP9 (Technical Notes). Added the
  error-message and release guarantees (AC4, AC6, AC7). Declared `numpy` explicitly. Strengthened
  the tests (exact 164-sample count, frame indices, seek-equals-sequential). Reset status to
  `ready` with unchecked ACs because the implementation will be erased and rebuilt.
- 2026-09-16: "Implement the project according to the docs in it. Commit each feature
  individually." Rebuild step 3 of [ADR 007](../../decisions/007-documentation-consolidation-for-rebuild.md).
  Added `src/extract_memes/frame_extractor.py` with `sample_frames` (a generator: sequential
  `cap.read()`, `step = max(1, round(native_fps / fps))`, stops at the first failed read) and
  `frame_at` (`CAP_PROP_POS_MSEC` seek). Both share an `_open` helper that raises
  `RuntimeError("Could not open video file: <path>")` and release the capture in `try/finally`.
  Declared `opencv-python-headless` and `numpy`. Added `tests/test_frame_extractor.py` covering
  every AC9 item, plus mocked-`VideoCapture` tests for release on early stop (AC7) and the
  `fps == 0` fallback (Q4), and a past-the-end `frame_at` error. Interpretation: AC9's "module
  skipped" is done per test through a shared `short_video` fixture in `tests/conftest.py`
  (skipped with a reason when `sample/short.mp4` is absent), so the fixture-free tests still run.
  Re-verified seek accuracy on the VP9 640x360 best download of the test video (302 frames, 26
  samples at 2 fps, indices 0/12/36/150/288 pixel-identical). All ACs checked; status
  `implemented`.
- 2026-09-17: The user asked how to fetch all the consecutive frames a meme appears on, noting that
  `frame_at` reopens the video on every call. Measured the alternatives on the 1080p download of
  `0TSqnhLXYfA` (Technical Notes): per-frame `frame_at` is ~10x slower than one open-and-seek per
  run of frames. The user asked for `frames_from` and decided against reusing one capture across
  runs (Q5). Added `frames_from` (AC10) and its tests (AC11). While writing them, found that
  `CAP_PROP_POS_MSEC` lags `CAP_PROP_POS_FRAMES` by a frame after a seek, so the timestamp is
  derived from the index. Verified on `sample/short.mp4` and on the 1080p VP9 file, where the known
  card at 99.56 s yields frames 2489–2498 (99.56–99.92 s) in 0.20 s, and the first frame is
  pixel-identical to `frame_at(path, 99.56)`. `sample_frames`, `frame_at`, and the pipeline are
  unchanged; status stays `implemented`.
- 2026-10-05: `sample_frames` timestamps now come from each frame's own presentation time
  (`CAP_PROP_POS_MSEC`) instead of `frame_index / native_fps` (AC1). The user reported low-res and high-res frames drifting apart, about
  1 s at 4 min and 15 s at 3500 s. On `_RHAQmLk0Es`, the 144p file decodes 82305 frames though
  its header implies 81945, because its frames are unevenly spaced (360 gaps of 40 ms among the
  usual 80 ms) while the header states a nominal 12.5 fps; the 1080p copy is regular. The header's
  frame count is only `duration × fps`, so counting frames from it could not show the difference.
  Checked against the best copy at four points across the video: the scan frame at its new timestamp
  matches the best frame at that time (mean difference about 3, against 22 to 71 ten seconds away).
  `frames_from` keeps `frame_index / native_fps`, since the best copy's spacing is regular. Test:
  mocked capture whose positions differ from `index / fps`.
