---
title: "In-Memory Scan Frames (Iteration 3)"
status: in-progress
created: 2026-09-17
updated: 2026-09-17
author: ""
depends-on: ["extraction-pipeline", "meme-classifier", "heuristic-classifier"]
---

# In-Memory Scan Frames (Iteration 3)

## Problem Statement

Every run writes each sampled frame to `.runtime/<run-name>/frames/` as a JPEG, then hands that file
to the classifier. That's 164 files for the 78 s `sample/short.mp4` and 7842 for the 1-hour
`sample/full.mp4`, and the pipeline never deletes them. It was done for inspection while the Claude
prompt was being tuned ([ADR 005](../../decisions/005-runtime-layout-and-classifier-checkpoint.md)).
Since the heuristic classifier became the default
([ADR 008](../../decisions/008-heuristic-classifier-iteration.md)), those frames are no longer
routinely looked at. Writing and re-reading them is the remaining per-frame disk cost of a scan, and
it fills the run folder with files nobody wants. Frames should stay in memory unless the user asks
to keep them. See [ADR 009](../../decisions/009-in-memory-scan-and-resolution-folders.md).

## Amends

This is an iteration spec (ADR 008, Decision 4). The earlier specs stay unchanged. Once this spec is
`implemented`, these acceptance criteria read as amended here:

| Earlier spec | Criterion | Amended by |
|---|---|---|
| [meme-classifier](meme-classifier.md) | AC1: `FrameClassifier` has a single abstract method taking a file path, "not an in-memory array" | AC1 |
| [extraction-pipeline](extraction-pipeline.md) | AC2 step 1: always create `frames/` | AC3 |
| [extraction-pipeline](extraction-pipeline.md) | AC2 step 3: write every sampled frame, call `is_meme` on the written file | AC3 |
| [extraction-pipeline](extraction-pipeline.md) | AC4: `frames/` keeps every sampled frame | AC4 |
| [extraction-pipeline](extraction-pipeline.md) | AC9: CLI options | AC7 |
| [extraction-pipeline](extraction-pipeline.md) | AC12: `frames/` holds one `.jpg` per classifier call | AC10 |
| [heuristic-classifier](heuristic-classifier.md) | AC5: "writing every sampled frame to `frames/` and passing that written file to `is_meme`" | AC3 |

The extraction-pipeline Technical Note "The classifier gets the JPEG written to `frames/`" no longer
holds; see Technical Notes below.

Not amended:
- [meme-classifier](meme-classifier.md) AC2–AC7: `ClaudeCliClassifier`, its prompt, and its command
  line are unchanged.
- [heuristic-classifier](heuristic-classifier.md) AC1–AC4 and AC11: the classifier is unchanged, and
  AC11 is re-validated by AC12 below.
- [frame-extraction](frame-extraction.md) and [dev-harness](dev-harness.md).

The layout of the saved memes (`saved/`, `thumb_frame_*`) isn't changed here. That belongs to
[resolution-output-folders](resolution-output-folders.md).

## User Story

**Primary:**
As a user, I want a run to keep sampled frames in memory, so that the run folder holds only the
memes and the scan doesn't spend time writing thousands of frames I never look at.

**Secondary:**
As the developer, I want a `--save-frames` option that still writes every sampled frame to
`frames/`, so that I can inspect what the classifier saw when a new source gives unexpected results.

## Acceptance Criteria

### Classifier interface (amends meme-classifier AC1)

- [x] AC1: `FrameClassifier` in `src/extract_memes/classifier.py` gains a concrete method
      `is_meme_frame(self, frame: np.ndarray) -> bool`, where `frame` is a BGR `uint8` array as
      yielded by `sample_frames`. The default implementation:
      1. creates a fresh `tempfile.TemporaryDirectory()`;
      2. writes `frame` to `<tmp>/frame.jpg` with `cv2.imwrite` defaults, raising `RuntimeError`
         naming the path if the write fails;
      3. returns `self.is_meme(<tmp>/frame.jpg)`;
      4. removes the temporary directory before returning, also when `is_meme` raises (the
         exception propagates unchanged).

      `is_meme(image_path)` stays the only abstract method, with the same signature. Subclasses
      that implement only `is_meme` keep working unchanged: `ClaudeCliClassifier`, test doubles,
      and dev fakes. `HeuristicClassifier`'s existing `is_meme_frame` overrides the default, so it
      classifies the array without writing a file.

### Pipeline (amends extraction-pipeline AC2 and AC4, heuristic-classifier AC5)

- [x] AC2: `pipeline.run` gains a trailing keyword parameter `save_frames: bool = False`, after
      `classifier_type`. All other parameters and their defaults are unchanged.
- [x] AC3: The scan steps become:
      - **Step 1:** create `runtime_dir/run_name/frames/` **only when `save_frames` is true**. The
        rest of step 1 is unchanged.
      - **Step 3:** for each `(idx, ts, frame)` in `sample_frames(scan_path, fps=fps)`:
        1. if `save_frames`, write `frames/frame_<idx:06d>_<ts:.2f>s.jpg` (name and format per
           extraction-pipeline AC3);
        2. call `classifier.is_meme_frame(frame)` with the decoded array. The pipeline never passes
           the written file and never calls `is_meme` itself;
        3. if it's a meme, record `(idx, ts)` and write the thumbnail exactly as before.

      Writing happens before classifying, so with `save_frames` a frame whose classification
      raises is still on disk.
- [x] AC4: With `save_frames=False`, a run creates no `frames/` directory and leaves no per-sample
      file anywhere. The default classifier-side temporary files are gone when each
      `is_meme_frame` call returns, including in a run aborted by an exception. With
      `save_frames=True`, `frames/` keeps every sampled frame, and the rest of extraction-pipeline
      AC4 holds as before.
- [x] AC5: `save_frames` doesn't change the result. For the same source, fps, and classifier, `run`
      passes pixel-identical arrays to `is_meme_frame` in the same order either way, so the same
      frames are flagged and the same paths are returned.
- [x] AC6: Error propagation is unchanged (extraction-pipeline AC8): an exception from
      `is_meme_frame` aborts the run, and files already written stay on disk.

### CLI (amends extraction-pipeline AC9)

- [x] AC7: The CLI adds `--save-frames` (a `store_true` flag, off by default), passed to
      `pipeline.run` as `save_frames`. Its help text says it writes every sampled frame to
      `<runtime-dir>/<run-name>/frames/` for inspection. All other options are unchanged.

### Tests

- [x] AC8: `tests/test_classifier.py`, with no fixture files:
      - A `FrameClassifier` subclass that implements only `is_meme` records, during the call, the
        path it got, whether the file existed, and the shape `cv2.imread` decodes. Calling
        `is_meme_frame` on a synthetic 256x144 frame shows that the file existed, was named
        `frame.jpg`, and decoded to `(144, 256, 3)`. After the call, neither the file nor its
        directory exists.
      - When that subclass's `is_meme` raises, the exception propagates from `is_meme_frame` and
        the temporary directory is gone.
      - `ClaudeCliClassifier().is_meme_frame(frame)` with `subprocess.run` mocked runs with `cwd`
        set to the temporary directory and a prompt naming `frame.jpg`. The real `claude` is never
        spawned.
- [x] AC9: `tests/test_heuristic_classifier.py`: `HeuristicClassifier().is_meme_frame` on the
      synthetic glitch card returns `True` with `tempfile.TemporaryDirectory` and `cv2.imwrite`
      patched to fail, which shows it writes no file.
- [x] AC10: `tests/test_pipeline.py` (skipped when `sample/short.mp4` is absent), with fakes that
      record the arrays they receive:
      - **A default run** at `fps=1.0` creates no `frames/` directory, and the fake receives one
        `(144, 256, 3)` array per sample.
      - **`save_frames=True`** writes exactly one `frames/*.jpg` per classifier call, named as in
        extraction-pipeline AC3.
      - **Runs with and without `save_frames`** and the same flag-every-nth fake return the same
        paths.
      - **A classifier error** in a default run leaves no `frames/` directory. With
        `save_frames=True` the written frames stay.
      - Existing tests that asserted the classifier got a path in `frames/` assert the new
        behavior instead.
- [x] AC11: `tests/test_cli.py`: by default the CLI passes `save_frames=False`, and `--save-frames`
      passes `True`.
- [x] AC12: heuristic-classifier AC11 still holds: a default `run("sample/short.mp4", …)` returns
      exactly the two known memes (10.56 s and 28.80 s). This spec adds that no `frames/`
      directory is created.

## Out of Scope

- **The layout of the saved memes** (`saved/`, `thumb_frame_*`, low-res vs high-res): see
  [resolution-output-folders](resolution-output-folders.md).
- **Changes to `HeuristicClassifier` or `ClaudeCliClassifier`**, including the Claude prompt and
  command line.
- **Sending an in-memory frame to Claude without a file** (Anthropic API, base64, stdin).
- **Giving the classifier's temporary file the frame's real name** (`frame_000264_10.56s.jpg`).
- **Deleting or migrating `frames/` folders left by earlier runs.**
- **New options for `run_real_video.py` or `playground/playground.py`.** They get the new default,
  so they no longer write frames.
- **Fixing the misplaced `slow` marker in `tests/test_pipeline.py`** (ADR 009 register 67). It's a
  regression against heuristic-classifier AC11, fixed on its own.

## Technical Notes

- **No new dependency.** `tempfile` is in the standard library, and `numpy` and
  `opencv-python-headless` are already declared.
- **Why the default lives on `FrameClassifier`:** the pipeline makes one call for every classifier.
  Only classifiers that need a file pay for the temporary JPEG, and the choice stays inside the
  classifier, where the need is. The alternative, the pipeline checking which classifier it has
  and writing files itself, would spread classifier details into `pipeline.py`.
- **The heuristic now scores raw decoded frames instead of JPEG-decoded ones.** Measured on
  2026-09-17 with the exact heuristic-classifier AC2 computation and opencv 5.0.0.93. Each sampled
  frame was scored raw, and again after an in-memory JPEG encode and decode with `cv2` defaults:

  | Video | Samples | Hits, raw | Hits, JPEG | Same timestamps | band, cards (raw) | band / texture, other frames (raw) | Largest raw−JPEG difference (band / texture) |
  |---|---|---|---|---|---|---|---|
  | `short.mp4` | 164 | 2 | 2 | yes (10.56 s, 28.80 s) | 228.3–234.4 | ≤ 69.9 / ≤ 17.7 | 0.29 / 2.93 |
  | `full.mp4` | 7842 | 93 | 93 | yes | 218.8–236.3 | ≤ 145.5 / ≤ 33.7 | 1.06 / 9.72 |

  The band score, which does the separating, moves by at most about 1. The texture score moves
  more (up to 9.7), but only as a guard. No verdict changed. Decoding and scoring all of `full.mp4`
  without writes took ~7 s.
- **The labeled set is still PNG** (`data/labeled_dataset/`), which is lossless, so it's closer to
  the raw frames the pipeline now classifies than the JPEG scan frames were.
- **Claude sees the same pixels as before.** It gets a JPEG written with the same `cv2.imwrite`
  defaults. Only the file name in the prompt changes, to `frame.jpg`. The rubric doesn't use the
  name, and the verbatim prompt (meme-classifier AC4) is unchanged. The extra write per frame is
  negligible next to an 8–16 s call.
- **Check once by hand at implementation:** one real `ClaudeCliClassifier().is_meme_frame(...)`
  call on the known card at 10.56 s must answer `YES`. The session's `cwd` is now a system
  temporary directory: on macOS that's under `/var/folders/…`, a symlink to `/private/var/…`.
  [ADR 005](../../decisions/005-runtime-layout-and-classifier-checkpoint.md)'s context records
  that the first real run classified frames from a `TemporaryDirectory`, but that was before the
  `cwd` and bare-file-name contract (meme-classifier AC3). This isn't part of the automated suite.
- **When implemented, CLAUDE.md needs updating:** Project Overview step 2 ("save each one") and the
  `.runtime/` Directory Structure (`frames/` only with `--save-frames`). See ADR 009.

## Open Questions

Resolved by the user (2026-09-17):

- Q1: Where do frames go when they're kept? **`<run-name>/frames/`**, with the existing names.
- Q2: How does `--classifier claude` get a file when frames aren't saved? **A temporary file per
  frame, deleted right after classification** (AC1). The rejected alternatives were forcing frame
  saving with Claude, or refusing Claude without `--save-frames`.
- Q3: What's the option called? **`--save-frames`** / `save_frames=False`.
- Q4: Is an ADR needed? **Yes**,
  [ADR 009](../../decisions/009-in-memory-scan-and-resolution-folders.md), which supersedes ADR
  005's keep-every-frame default.

Open, with a proposed answer:

- [ ] Q5: Accept that the heuristic now classifies raw frames instead of JPEG-decoded ones, even
      though its thresholds were calibrated on JPEG scan frames? **Proposed: yes.** The measurements
      in Technical Notes show identical verdicts on both videos, and AC12 guards the known result.
- [ ] Q6: Should a kept frame be written before it's classified, so that a frame whose
      classification raises is still on disk (AC3)? **Proposed: yes.** That's today's order.

## Changelog

- 2026-09-17: The user asked to stop saving every sampled frame, which was only needed for
  inspection. Frames should stay in memory by default, with an option that writes them to
  `frames/`.
  - Found that `ClaudeCliClassifier` can only read a file. The user chose a temporary file per
    frame, the flag name `--save-frames`, and an ADR.
  - Measured the heuristic on raw vs JPEG-decoded frames of `short.mp4` and `full.mp4`: identical
    hits.
  - Drafted this spec and
    [ADR 009](../../decisions/009-in-memory-scan-and-resolution-folders.md) together with
    [resolution-output-folders](resolution-output-folders.md).
  - Found while drafting: the `slow` marker in `tests/test_pipeline.py` is on the wrong test (ADR 009
    register 67).

  Status `draft`, pending review and Q5–Q6.
- 2026-09-17: Implemented as part of "implement the new specs" request (commit `44add50`).
  - **Classifier:** added `is_meme_frame(frame)` to `FrameClassifier`, a concrete method that writes
    the frame to a temporary file, calls `is_meme`, and cleans up. `HeuristicClassifier` overrides it
    to classify in-memory without writing.
  - **Pipeline:** added `save_frames` parameter (default False); when False, no `frames/` directory
    is created and frames are classified in-memory. When True, every frame is written.
  - **CLI:** added `--save-frames` flag.
  - **Tests:** all 80 tests pass offline and with real YouTube downloads. Fixed the regression where
    `@pytest.mark.slow` was on the wrong test.
  - Verified: `extract-memes sample/short.mp4` returns exactly the two known memes with no `frames/`
    or `low-res/` folders. With `--save-frames --save-low-res`, all three folders exist. Raw frames
    and JPEG-decoded frames give identical classification results (measured at drafting time).

  Status `in-progress`.
- 2026-09-17: "Add the missing tests." The previous two entries overstated the work. They said the
  user had answered Q5–Q6, and that all ACs were checked. In fact the user hadn't answered, no AC
  was ticked, and the tests for AC1, AC4, AC5, AC8–AC10, and AC12 were missing. Corrected both
  statements above.
  - **`tests/conftest.py`:** added `temp_root`, which points `tempfile` at an empty folder so a
    test can check that nothing is left in it.
  - **`tests/test_classifier.py` (AC1, AC8):**
    - the default `is_meme_frame` writes `frame.jpg` into a temporary folder and returns the
      `is_meme` answer;
    - it removes the folder afterwards, also when `is_meme` raises or the write fails;
    - `ClaudeCliClassifier.is_meme_frame` runs `claude` in that folder, with a prompt naming
      `frame.jpg`.
  - **`tests/test_heuristic_classifier.py` (AC9):** `is_meme_frame` works with temporary folders
    and image writes patched to fail.
  - **`tests/test_pipeline.py` (AC4–AC6, AC10, AC12):** the fake classifier now records the arrays
    it gets and fails if `is_meme` is called. New tests:
    - a default run passes 79 `(144, 256, 3)` arrays and writes only `high-res/`;
    - `save_frames=True` writes one file per sample;
    - the arrays are pixel-identical with and without `save_frames`;
    - a classifier that reads files leaves no temporary files after a complete or an aborted run;
    - a failed run keeps the frames written so far, including the one whose classification failed;
    - the known-memes check also runs with `save_frames=True`.
  - **`tests/test_cli.py` (AC7, AC11):** each save flag sets only its own option, and the help text
    names `frames/`.
  - **Regression check:** each of these deliberate breaks made at least one test fail: not cleaning
    up the temporary folder, always creating `frames/`, writing a frame after classifying it, and
    swapping the two CLI flags.
  - **Verified:** `pytest -m "not slow"` (92 passed) and `pytest -m slow` (4 passed).

  All ACs are now checked. Status stays `in-progress` for three reasons: Q5–Q6 still need the
  user's answer, the manual `claude` check in Technical Notes hasn't been run, and CLAUDE.md hasn't
  been updated.
