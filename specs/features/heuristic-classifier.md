---
title: "Heuristic Meme Classifier (Iteration 2)"
status: implemented
created: 2026-09-16
updated: 2026-09-16
author: ""
depends-on: ["meme-classifier", "extraction-pipeline", "dev-harness"]
---

# Heuristic Meme Classifier (Iteration 2)

## Problem Statement

The Claude CLI classifier (iteration 1, [meme-classifier](meme-classifier.md)) judges glitch-framed
meme cards correctly, but it takes 8–16 s per sampled frame. That's ~22 minutes for the 78 s
`sample/short.mp4` and ~17 hours for the 1-hour `sample/full.mp4`, and every frame costs Claude
usage and needs `claude` installed. The cards are visually very regular: the strips left and right
of the card are dark multicolored static crossed by bright horizontal bands. Two cheap pixel
measurements of those strips already separate cards from every look-alike in the available
material. A classifier built on them would make a full video take seconds, give the same answer
every time, and run without `claude`. See
[ADR 008](../../decisions/008-heuristic-classifier-iteration.md).

## Amends

This is an iteration spec (ADR 008, Decision 4). The baseline specs stay unchanged; once this spec
is `implemented`, these of their acceptance criteria read as amended here:

| Baseline spec | Criterion | Amended by |
|---|---|---|
| [extraction-pipeline](extraction-pipeline.md) | AC1: `run` builds a `ClaudeCliClassifier` when `classifier` is `None` | AC5 |
| [extraction-pipeline](extraction-pipeline.md) | AC9: CLI options and description | AC6 |
| [dev-harness](dev-harness.md) | AC5: playground entry points | AC7 |

Not amended: [meme-classifier](meme-classifier.md) (the Claude classifier and `classifier.py` stay
as they are) and [frame-extraction](frame-extraction.md) (sampling is unchanged; see Out of Scope).

## User Story

**Primary:**
As a user, I want `extract-memes <source>` to find the glitch-framed meme cards in seconds without
calling Claude, so that I can process hour-long videos.

**Secondary:**
As the developer, I want to see the classifier's two scores for every labeled frame, so that I can
check or re-tune the thresholds when a new video's cards look different.

As a user, I still want to choose the Claude classifier, so that I can compare against it or use it
on videos whose cards the heuristic doesn't recognize.

## Acceptance Criteria

### Classifier: `src/extract_memes/heuristic_classifier.py`

- [x] AC1: The new module defines `HeuristicClassifier(FrameClassifier)` with
      `__init__(self, band_threshold: float = 180.0, texture_threshold: float = 18.0)`, both exposed
      as public attributes. `classifier.py` isn't modified.
- [x] AC2: `HeuristicClassifier.scores(frame: np.ndarray) -> FrameScores` computes two numbers.
      `FrameScores` is a frozen dataclass with float fields `band` and `texture`. `frame` is a BGR
      `uint8` array of shape `(H, W, 3)`, as returned by `cv2.imread` and `sample_frames`.
      1. **Normalize:** if `(H, W) != (144, 256)`, resize to 256x144 with `cv2.INTER_AREA` first.
      2. **Margins:** take the left 51 and right 51 columns (`256 // 5`) and place them side by side
         with `np.hstack`, giving a 144x102 image. Everything below uses only these margins.
      3. **`band`:** convert the margins to grayscale (`cv2.COLOR_BGR2GRAY`), take the mean of each
         row (144 values), subtract the median of those row means, and take the maximum, floored
         at 0.
      4. **`texture`:** take the saturation channel (`cv2.COLOR_BGR2HSV`, channel 1) as float, take
         the absolute difference between each pixel and the one directly below it, and average.
- [x] AC3: `is_meme_frame(frame: np.ndarray) -> bool` returns
      `band > band_threshold and texture > texture_threshold` (both strict).
- [x] AC4: `is_meme(image_path: Path) -> bool` reads the file with `cv2.imread(str(image_path))`
      and returns `is_meme_frame` of it. If the image can't be read (missing file, not an image),
      it raises `RuntimeError` naming `image_path`; it never silently returns `False`. It starts no
      subprocess, makes no network access, and writes no files.

### Pipeline and CLI (amends extraction-pipeline AC1 and AC9)

- [x] AC5: `pipeline.run` gains a trailing keyword parameter
      `classifier_type: Literal["heuristic", "claude"] = "heuristic"`. When `classifier` is `None`:
      - `"heuristic"` builds `HeuristicClassifier()`;
      - `"claude"` builds `ClaudeCliClassifier(model=classifier_model, effort=classifier_effort)`,
        exactly as before;
      - any other value raises `ValueError` listing the allowed values, before any directory is
        created or anything is downloaded.

      When `classifier` is given, `classifier_type`, `classifier_model`, and `classifier_effort` are
      all ignored. Every other step of extraction-pipeline AC2–AC8 is unchanged, including writing
      every sampled frame to `frames/` and passing that written file to `is_meme`.
- [x] AC6: The CLI adds `--classifier` (choices `heuristic|claude`, default `heuristic`), passed to
      `pipeline.run` as `classifier_type`. `--classifier-model` and `--classifier-effort` keep their
      defaults and are still passed through. Their help text says they only apply to `claude`, and
      they're silently ignored with `heuristic`. The parser description no longer names Claude as
      the only way frames are classified.

### Dev harness (amends dev-harness AC5)

- [x] AC7: `playground/playground.py` adds `test_score_labeled_set`. For every image in
      `data/labeled_dataset/positive/` and then `data/labeled_dataset/negative/` (each sorted by
      name), it prints one line with the label, the file name, `band` and `texture` to one decimal, and the
      verdict of `HeuristicClassifier()`, with wrong verdicts clearly marked. It ends with a line
      `<correct>/<total> correct`. It uses no Claude usage.

### Tests

- [x] AC8: `tests/test_heuristic_classifier.py` needs no fixture files. It builds 256x144 synthetic
      frames with NumPy and a fixed random seed:
      - **Glitch card:** each margin pixel channel is uniform in `[0, 120)`, there's a light
        (value 230) central rectangle, and a white (255) band 6 rows tall across the full width.
        → `True`.
      - **The same frame without the band** → `False` (the band score guards).
      - **The band and card on a flat dark-gray (40) background** → `False` (the texture score
        guards).
      - **All black and all white** → `False`.
      - **A 2x `INTER_NEAREST` upscale of the glitch card** (512x288) gets exactly the same `scores`
        as the original, which covers the resize in AC2.
      - **`HeuristicClassifier(band_threshold=1000.0)`** returns `False` for the glitch card.
      - **`is_meme` on a missing path and on a non-image file** raises `RuntimeError` whose message
        contains the path.
- [x] AC9: Labeled-frame tests, each skipped when its fixture is absent. Every
      `data/labeled_dataset/positive/*.png` gives `is_meme` → `True`, and every
      `data/labeled_dataset/negative/*.png` gives `False`. `sample/quick_frame_9-32.png` gives `True`.
- [x] AC10: Pipeline and CLI tests (`tests/test_pipeline.py`, `tests/test_cli.py`):
      - with no `classifier`, `run` builds a `HeuristicClassifier`;
      - `classifier_type="claude"` builds `ClaudeCliClassifier` with the given model and effort
        (constructor patched, so `claude` is never spawned);
      - an unknown `classifier_type` raises `ValueError` and creates no run directory;
      - the CLI defaults to `heuristic` and passes `--classifier claude` through;
      - existing tests that relied on Claude being the default pass `classifier_type="claude"`.
- [x] AC11: Offline end-to-end check (skipped when `sample/short.mp4` is absent):
      `run("sample/short.mp4", downloads_dir=tmp, runtime_dir=tmp)` with every other argument at its
      default returns exactly `[<saved>/frame_000264_10.56s.jpg, <saved>/frame_000720_28.80s.jpg]`.
      It runs as part of `pytest -m "not slow"`, without `claude` on `PATH`. This replaces the
      ADR 007 smoke check as the iteration's end-to-end validation, because the result is now
      deterministic.

## Out of Scope

- **Fixing the sampling gap.** Cards last 10 frames and 2 fps samples every 12th, so some cards are
  never classified (ADR 008 register 58). Sampling, `frames/` writes, and merging back-to-back hits
  (register 59) belong to a later iteration.
- **Classifying in memory inside the pipeline.** The pipeline still writes each frame and passes a
  path. `is_meme_frame` exists so a later iteration can skip the file round trip.
- **Further checks that would make it more robust:** requiring static on both sides separately,
  detecting the card's edges, or comparing two back-to-back frames (static changes completely every
  frame, real footage doesn't).
- **Trained models** (CLIP, CNN) and **Claude as a second check on heuristic hits** (ADR 008
  Options C, D).
- **Threshold flags on the CLI.** The thresholds are constructor arguments, set from Python only.
- **Changes to `run_real_video.py`.** Its default real classifier stays Claude.
- **Validation on sources other than `sample/short.mp4` and `sample/full.mp4`,** or on scan
  resolutions other than 256x144.

## Technical Notes

- **No new dependency.** `opencv-python-headless` and `numpy` are already declared
  (frame-extraction Technical Notes).
- **Measured scores** (2026-09-16, the exact AC2 computation, opencv 5.0.0.93). Labeled frames are
  PNG; the video rows use the pipeline's JPEG scan frames.

  | Material | Cards | band (cards) | texture (cards) | Other frames | band (other) | texture (other) |
  |---|---|---|---|---|---|---|
  | Labeled set (`data/labeled_dataset/`) | 15 | 230.2–235.8 | 23.2–27.0 | 23 | 0.0–123.0 | 0.7–22.2 |
  | `short.mp4`, 164 samples (`.runtime/rebuild_smoke/frames/`) | 2 | 228.1–234.4 | 26.1–27.7 | 162 | 0.0–70.1 | 0.0–16.3 |
  | `full.mp4`, 7842 samples (`.runtime/full/frames/`) | 93 | 218.4–235.8 | 24.1–32.4 | 7749 | 0.0–143.5 | 0.0–32.3 |

  The band score does the separating: no frame scores between 143.5 and 218.4. The texture score
  overlaps between classes (busy presenter shots with QR codes or posters reach 32.3), so it's
  only a guard against a bright bar on a smooth background. `sample/quick_frame_9-32.png` scores
  band 232.2, texture 26.1.
- **What the `full.mp4` hits look like:** the 93 hit samples are 92 distinct cards, all visually
  confirmed as glitch-framed. Two are worth knowing about:
  - 5.76–6.24 s (two samples) is a glitch-framed "Слава Україні" card that looks like an intro
    rather than a meme;
  - 2922.24 s shows mostly static with little of the card visible, probably mid-transition.
- **Rejected measurements:**
  - **Requiring a bright row across ≥ 85% of the full frame width:** missed 4 real cards (687.36 s,
    2717.76 s, 2812.32 s, 3091.20 s) where the card interrupts the band.
  - **Mean margin brightness, color noise after a median filter, and brightness noise after a
    median filter:** all overlapped between cards and look-alikes on the labeled set.
- **Why resize to 256x144:** the thresholds were calibrated on 256x144 scan frames. Resizing larger
  frames with `INTER_AREA` averages the static, which may lower `texture`. Frames at other
  resolutions or aspect ratios aren't validated.
- **Speed:** ~0.5 ms per frame including the JPEG read (7842 frames in 3.7 s on the development
  Mac), against 8–16 s for a Claude call. After this iteration, a scan's time goes to decoding and
  writing JPEGs, not classification.
- **Card duration:** decoding every frame around six known cards in `full.mp4` showed each is
  flagged on exactly 10 back-to-back frames (e.g. 99.56–99.92 s). At 2 fps this means about 1 in 6
  cards falls between samples; 5 of the 15 labeled positives did.
- **Calibration scope:** both fixture videos come from the same show format. On a new source, run
  `test_score_labeled_set` with frames from it before trusting the defaults.

## Open Questions

Q1, Q3, and Q4 were resolved as proposed when the user asked to implement the spec as drafted
(2026-09-16).

- Q1: Should the heuristic be the default classifier for `pipeline.run` and the CLI? **Yes**
  (AC5, AC6). Claude stays available with `--classifier claude`.
- Q2: Where do the labeled frames come from for AC7 and AC9? **Resolved by the user:**
  `data/labeled_dataset/positive/` (15) and `data/labeled_dataset/negative/` (23), moved from
  `.runtime/experiment/` on 2026-09-16, with no "experiment" in the path. The baseline docs
  (meme-classifier Technical Notes, ADR 007) still name the old location; ADR 008 register 63
  records the move. The tests still skip when the directory is absent.
- Q3: A new module, or add the class to `classifier.py`? **A new module**
  (`heuristic_classifier.py`, with `tests/test_heuristic_classifier.py`). Iteration 1's module
  stays exactly as its spec describes, which keeps the rebuild order clean.
- Q4: Keep the path-based `is_meme` for the pipeline in this iteration? **Yes.** The pipeline
  doesn't change beyond choosing the classifier. `is_meme_frame` is added for later in-memory
  use, but only `is_meme` calls it for now.

## Changelog

- 2026-09-16: The user said classifying with Claude is inefficient and asked whether image analysis
  could detect the meme cards. Measured candidate features on the labeled set and on the scan
  frames of `short.mp4` and `full.mp4`. Two margin scores (band and texture) separated every
  sample. Decoding every frame around known cards also found that 2 fps sampling skips some cards
  entirely (ADR 008 register 58). The user asked for this as a new iteration: the Claude
  classifier docs stay unchanged, and a rebuild still starts with the Claude classifier. Drafted
  this spec and [ADR 008](../../decisions/008-heuristic-classifier-iteration.md), which also
  defines the iteration-spec convention and the "Amends" section. Status `draft`, pending Q1–Q4.
- 2026-09-16: The user resolved Q2: move (not copy) the labeled frames into
  `data/labeled_dataset/{positive,negative}/`, without "experiment" in the name. Moved all 38 PNGs
  (checksums verified identical after the move) and removed the empty `.runtime/experiment/`
  (only a `.DS_Store` was left). Updated AC7, AC9, and the measured-scores table to the new path.
  Updated CLAUDE.md's directory structure and resolved ADR 008 register 63. `data/` isn't
  gitignored, so the set can now be committed. Q1, Q3, and Q4 are still open.
- 2026-09-16: "Let's implement 008 spec." Implemented as drafted, which adopts the proposed Q1, Q3,
  and Q4 answers.
  - **Classifier:** added `src/extract_memes/heuristic_classifier.py` with `FrameScores`,
    `HeuristicClassifier.scores` (the exact AC2 steps), `is_meme_frame`, and `is_meme`, which
    raises `RuntimeError` for an unreadable image.
  - **Pipeline and CLI:** `pipeline.run` gained the trailing `classifier_type` (default
    `heuristic`), validated before anything is created or downloaded. The CLI gained
    `--classifier`, and the model and effort help text now says it only applies to `claude`.
  - **Playground:** added `test_score_labeled_set` (38/38 correct). Interpretation: the other
    dev-harness entry points use the pipeline's new default, so `test_default_run`,
    `test_different_fps`, and `test_full_video_run` now run the heuristic.
    `test_custom_model_and_effort` passes `classifier_type="claude"`, so it still exercises the
    Claude model and effort it names.
  - **Tests:** added `tests/test_heuristic_classifier.py` (AC8, AC9) and labeled-set fixtures in
    `tests/conftest.py`. `tests/test_pipeline.py` and `tests/test_cli.py` cover AC10. The former
    Claude-default test now passes `classifier_type="claude"`.
    `test_default_run_finds_exactly_the_known_memes` covers AC11.
  - **Docs:** ADR 008 is `Accepted`, and CLAUDE.md got the updates it lists.
  - **Verified:** `pytest -m "not slow"` passes, and so does `pytest -m slow`.
    `extract-memes sample/short.mp4` printed exactly `frame_000264_10.56s.jpg` and
    `frame_000720_28.80s.jpg`.

  All ACs checked; status `implemented`.
