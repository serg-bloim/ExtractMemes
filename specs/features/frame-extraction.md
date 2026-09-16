---
title: "Frame Extraction"
status: ready
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

## Acceptance Criteria

- [ ] AC1: `src/extract_memes/frame_extractor.py` exposes
      `sample_frames(video_path: Path, fps: float = 2.0) -> Iterator[tuple[int, float, np.ndarray]]`,
      which yields `(frame_index, timestamp_seconds, frame)`. `frame_index` is the 0-based index of
      the decoded frame in the source file (not a sample counter). `timestamp_seconds` is
      `frame_index / native_fps`. Items come in strictly increasing order.
- [ ] AC2: Sampling step: `native_fps = cap.get(cv2.CAP_PROP_FPS) or fps`,
      `step = max(1, round(native_fps / fps))` using Python's built-in `round` (half-to-even).
      Every `step`-th decoded frame is yielded, starting at index 0. So the effective rate is
      `native_fps / step`, which isn't always exactly `fps`. For a 25 fps source at the default
      `fps=2.0`: `round(12.5) == 12`, giving 2.083 samples/s at `0.00s, 0.48s, 0.96s, …`. This is
      the documented, intended behavior (see Open Questions Q3).
- [ ] AC3: `sample_frames` decodes sequentially with `cap.read()` and never seeks per sample. It
      doesn't use `cv2.CAP_PROP_FRAME_COUNT` to decide how many frames to read (that property is
      unreliable, see Technical Notes). It stops at the first failed read.
- [ ] AC4: It also exposes `frame_at(video_path: Path, timestamp_seconds: float) -> np.ndarray`.
      This seeks with `cap.set(cv2.CAP_PROP_POS_MSEC, timestamp_seconds * 1000)` and reads one
      frame. If no frame can be read, it raises `RuntimeError` naming both the timestamp and the
      path.
- [ ] AC5: Both functions use `cv2.VideoCapture` (OpenCV's bundled FFmpeg backend). No system
      `ffmpeg`/`ffprobe` binary is required.
- [ ] AC6: If the video can't be opened (`not cap.isOpened()`: missing file, unsupported codec),
      both functions raise `RuntimeError("Could not open video file: <path>")`. `sample_frames` is a
      generator, so it raises on the first `next()`, not when it's called.
- [ ] AC7: The `VideoCapture` is always released (`try/finally`), including when the consumer stops
      iterating early or an exception propagates.
- [ ] AC8: Frames are returned exactly as decoded: BGR `numpy.ndarray` at the file's native
      resolution, with no resizing or color conversion. That's what `cv2.imwrite` expects.
- [ ] AC9: Unit tests run against `sample/short.mp4` (module skipped if that fixture is absent) and
      check:
      at `fps=1.0`, 79 frames, all within the range 70–85;
      at the default `fps=2.0`, exactly 164 frames with `frame_index` values `0, 12, 24, …`;
      timestamps strictly increasing;
      every frame is `(144, 256)`;
      `frame_at(short.mp4, 10.0)` has shape `(144, 256)`;
      for several indices `i` (e.g. 0, 12, 150, 288), `frame_at(short.mp4, i / 25)` is
      pixel-identical to the `i`-th sequentially decoded frame;
      and a missing file raises `RuntimeError` on iteration.

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
  decoded frame is sampled, with timestamps based on the requested rate).

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
