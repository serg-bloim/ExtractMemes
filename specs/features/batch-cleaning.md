---
title: "Batch Cleaning: One Less Distorted Image per Meme"
status: implemented
created: 2026-09-17
updated: 2026-09-17
author: ""
depends-on: ["extraction-pipeline", "frame-extraction", "heuristic-classifier"]
---

# Batch Cleaning: One Less Distorted Image per Meme

## Problem Statement

A meme now comes out of the pipeline as a batch of ~10 consecutive full-quality frames in
`high-res/meme_<n:03d>/`. Every frame of a batch shows the same still card, but each is crossed by
VHS-style glitch bands — bright, dark and chroma-shifted horizontal stripes — that sit over the card
itself, and no single frame is free of them. Picking any one frame therefore means keeping its
bands. The bands move vertically from frame to frame while the card stays put, so most pixels have
an undistorted value in most frames of the batch, and the batch can be reduced to one image that is
far cleaner than any frame in it. The result doesn't have to be perfect.

## Amends

This is an iteration spec (ADR 008, Decision 4). Once this spec is `implemented`, these acceptance
criteria read as amended here:

| Earlier spec | Criterion | Amended by |
|---|---|---|
| [extraction-pipeline](extraction-pipeline.md) | Out of Scope: "Refining a batch into one resulting image … the intended next step" | This spec as a whole |
| [extraction-pipeline](extraction-pipeline.md) | AC1: `run`'s signature | AC6 |
| [extraction-pipeline](extraction-pipeline.md) | AC2 step 1 (folders) and steps 6–7 (batches, return value) | AC7, AC8 |
| [extraction-pipeline](extraction-pipeline.md) | AC9: CLI options | AC9 |
| [extraction-pipeline](extraction-pipeline.md) | AC12, AC16, AC19: returned paths are the batch files | AC10 |
| [dev-harness](dev-harness.md) | AC5: the playground entry-point table | AC11 |

Not amended: the scan pass, `frames/`, `low-res/`, the batch folders and their file names, run
names, error propagation, and both classifiers. Cleaning reads the batch and writes one more file.

## User Story

**Primary:**
As a user, I want each meme delivered as one image with the glitch bands mostly gone, so that I get
a usable picture of the card instead of ten damaged ones.

**Secondary:**
As the developer, I want to compare the candidate combination methods on real batches, so that the
default is chosen by looking at results rather than by argument.

## Acceptance Criteria

### Module: `batch_cleaner`

- [x] AC1: `src/extract_memes/batch_cleaner.py` exposes
      `combine(frames: Sequence[np.ndarray], method: str = DEFAULT_METHOD, *, normalise: bool = True, flatten_rows: bool = False) -> np.ndarray`,
      plus `METHODS`, `DEFAULT_METHOD` and `banding_score(frame) -> float`. It does no I/O, never
      resizes, and is deterministic. `METHODS` is
      `("best_single", "median", "trimmed_mean", "consensus", "row_pick", "darkest", "darkest_mean", "clean_rows")`, and `DEFAULT_METHOD` is
      `"clean_rows"` ([ADR 011](../../decisions/011-clean-rows-as-the-default.md), which supersedes
      ADR 010's `trimmed_mean`).
- [x] AC2: `combine` returns a BGR `uint8` array of the input shape. It raises `ValueError` when
      `method` isn't in `METHODS` (the message names them), when the batch is empty, and when the
      frames don't all have the same shape. A one-frame batch returns a copy of that frame.
- [x] AC3: With `normalise=True` (the default), each frame's overall brightness is aligned before
      combining: means are taken over the middle 60% of the width (the card, not the static
      margins), and each frame is shifted by `median(means) - its mean`. This removes the drift a
      real batch has (measured 103.1 → 108.1 over ten frames).
- [x] AC4: The methods, on the normalised `float32` stack:
      - `best_single`: return the input frame with the lowest `banding_score` — the control, not a
        merge. Computed before normalisation, on the frames themselves.
      - `median`: `np.median(stack, axis=0)`.
      - `trimmed_mean`: sort along the frame axis, drop `max(1, N // 5)` values at each end, mean
        the rest.
      - `consensus`: frames within 6 gray levels of the per-pixel median "agree"; where at least
        `max(3, N // 3)` agree, average them, elsewhere use the median, blending the two by the
        agreement count so the switch leaves no outline.
      - `row_pick`: per row, copy the row of the frame whose row deviates least from the median row
        (deviations smoothed along rows with `cv2.blur` so a single noisy row can't flip the
        choice).
      - `darkest`: per pixel, take the frame where it is darkest. The frame is chosen by luminance
        (`0.299 R + 0.587 G + 0.114 B`) and all three channels are copied together, so the result
        keeps a real colour instead of a per-channel minimum's cast.
      - `darkest_mean`: average the darkest `max(1, N // 3)` frames per pixel, ranked the same way.
      - `clean_rows`: judge each `(frame, row)` by how far the row's ends are from black — the
        outer 1/20 of the width at each side, which is letterbox bar in an undamaged row. Rows
        within 8 gray levels of the batch's darkest ends for that row are "good" and averaged;
        the 3 least affected rows are always kept as well, so a row that's damaged in every frame
        still has something to average.

      Every method except `best_single` runs over horizontal slices of 256 rows so a
      full-resolution batch stays in bounded memory.
- [x] AC5: `banding_score(frame)` is `mean |row_mean[i] - row_mean[i-1]|` over the card columns:
      the roughness of the row-brightness profile, which a horizontal band spikes. With
      `flatten_rows=True`, `combine` additionally subtracts whatever row-constant brightness is
      left after the merge (`row_mean - blur(row_mean)`), which also flattens genuine wide
      horizontal structure — hence off by default.

### Pipeline

- [x] AC6: `pipeline.run` gains a trailing keyword parameter
      `clean_method: str | None = batch_cleaner.DEFAULT_METHOD`. A value outside `METHODS` (and not
      `None`) raises `ValueError` before anything is downloaded or created.
- [x] AC7: Step 1 also creates `runtime_dir/run_name/clean/` when `clean_method` is not `None`, and
      `high-res/` only when `save_high_res` is true (AC13).
- [x] AC8: In step 6, the frames of a batch are collected in memory, and when the batch is finished
      `combine(batch, clean_method)` is written to `clean/meme_<n:03d>.png`. A batch that matched no
      frame produces no file. With `clean_method=None` nothing is combined and no `clean/` folder is
      made.
- [x] AC13: `run` gains a trailing keyword parameter `save_high_res: bool = False`. The batch frames
      are written to `high-res/meme_<n:03d>/` (and the batch folder created) only when it's true;
      by default a batch is combined from memory and nothing full-quality is kept. `clean_method`
      is `None` **and** `save_high_res` false would save nothing at all, so that combination raises
      `ValueError` before anything is downloaded or created. The CLI adds `--save-high-res`.
- [x] AC9: Step 7 returns the `clean/` paths in meme order when cleaning is on, and the batch frame
      paths (as before) when it's off. The CLI prints the returned paths and gains
      `--clean-method` with `none` plus every name in `METHODS` as choices, defaulting to
      `DEFAULT_METHOD`, where `none` passes `clean_method=None`. Its help text names
      `<runtime-dir>/<run-name>/clean/`.

### Dev harness

- [x] AC11: `playground/playground.py` gains `test_compare_cleaners_on_real_batch()` and
      `test_compare_cleaners_on_short_video()`. Both take one meme batch the way the pipeline
      would (`frames_from` around the timestamp, kept if the heuristic flags the downscaled frame)
      and write, under `.runtime/_playground/clean/<label>/`: `inputs/frame_<i:02d>.png`, one
      `<NN>_<method>.png` per method, a labelled contact sheet `sheet.png`, and `detail.png`, the
      same 100% centre crop from every method. Each prints a table of method, elapsed ms,
      `banding_score`, and distance from the `trimmed_mean` result, plus the best and worst input
      frame's score. A missing video or an empty batch prints why and returns.

### Tests

- [x] AC10: `tests/test_pipeline.py` (skipped when `sample/short.mp4` is absent): a default run
      returns `clean/meme_<n>.png`, one per non-empty batch, decoding to the frame size;
      `clean_method=None` returns the batch frames and creates no `clean/`; an unknown method
      raises before anything is written; a batch that matches nothing leaves `clean/` empty; and
      the cleaned image differs from every frame it was made from while sitting closer to the batch
      than the batch's own spread. The real-URL `slow` tests expect the returned paths in `clean/`.
      `tests/test_cli.py` covers the default, an explicit method, `none`, an invalid value (exit 2)
      and the help text.
- [x] AC12: `tests/test_batch_cleaner.py`, fixture-free and deterministic: a synthetic clean card
      plus ten copies, each with a bright and a dark band at rows no other copy reuses and a
      brightness offset. Every merging method except `darkest` beats **every** input frame's mean
      absolute error
      against the clean card; `median` and `trimmed_mean` reconstruct it to within 1 gray level
      once the constant brightness offset is removed; `best_single` returns the one band-free
      frame; `banding_score` is higher for a banded frame; `flatten_rows` lowers the banding score
      of a merge that kept a band; shape, dtype and determinism hold; `combine` writes no file
      (`cv2.imwrite` patched to raise); and the three `ValueError` cases raise. `darkest` and
      `darkest_mean` get their own tests on a batch whose bands only brighten, where both beat
      every input frame, plus one pinning `darkest`'s failure on a batch that also has a dark band.
      `clean_rows` gets a letterboxed synthetic card with colourful noise bands that lift the bars:
      it beats every input frame and reconstructs the card to within 1 gray level, and a second
      test covers rows banded in every frame, where the least affected must still be used and the
      result stay finite.

## Out of Scope

- **Cropping to the card.** The cleaned image is the whole frame, static margins included. Finding
  the card's edges is its own problem (user decision, 2026-09-17).
- **Aligning frames before combining.** Measured unnecessary: a ±25 px vertical shift search picks
  `dy=0` for every frame of a real batch, and phase correlation gives < 0.05 px.
- **Sharpening, upscaling, colour correction, or removing the static in the margins.**
- **Combining across batches**, or merging two batches that show the same card.
- **A `--flatten-rows` CLI flag.** The option is available from Python only, like `window_seconds`.
- **Choosing the method per meme** (for example by score). One method per run.

## Technical Notes

- **No new dependency:** `numpy` and `opencv-python-headless` are already declared.
- **Why this works at all — measurements on a real 10-frame 1080p batch** (99.56 s of the source of
  `sample/full.mp4`, `0TSqnhLXYfA`), 2026-09-17:
  - frames are geometrically stable (see Out of Scope);
  - a consensus exists for about half the card: 55.4% of pixels have 5 of 10 frames agreeing within
    6 gray levels, 48.3% have 6 of 10;
  - the distortion is dense, not sparse: each frame differs from the batch's trimmed mean by 26–36
    gray levels on average, and the per-pixel temporal std in the card area is 36.9.
- **Comparison results** (`banding_score`, lower is less banded; best input frame in brackets):

  | Batch | best_single | median | trimmed_mean | consensus | row_pick | darkest | darkest_mean | clean_rows |
  |---|---|---|---|---|---|---|---|---|
  | 99.56 s (10 frames) | 1.58 | 1.36 | 1.16 | 1.36 | 3.17 | **1.12** | 1.14 | 1.34 |
  | 687.36 s (10 frames) | 1.40 | 1.24 | **1.07** | 1.24 | 2.80 | — | — | — |
  | 2812.32 s (20 frames) | 1.11 | 0.80 | 0.74 | 0.81 | 1.41 | **0.68** | 0.69 | 0.94 |

  The score measures banding only, so it ranks `darkest` first even though that method also darkens
  the image; the user judged `darkest`/`darkest_mean` best by eye, and `clean_rows` keeps the
  margins clearly cleaner than `trimmed_mean` at normal brightness.

  By eye, `median`, `trimmed_mean` and `consensus` all remove the wide bright band that ruins
  `best_single`; `trimmed_mean` is the smoothest of them and keeps the card's text sharp, while
  `row_pick` leaves visible seams. See [ADR 010](../../decisions/010-batch-cleaning-by-trimmed-mean.md).
- **`clean_rows` needs letterbox bars.** The source is a vertical video in a 16:9 frame, so an
  undamaged row's far ends are black and any band — bright *or* colourful noise — lifts them. That
  makes the ends a detector the card's own content can't confuse. Measured on the two batches:
  3.6 and 4.5 frames pass per row on average, and 15.4% / 0.1% of rows are damaged in **every**
  frame, which is what the least-affected fallback is for. It's also the fastest method
  (64 ms / 125 ms). On a source without bars the ends are content, and the method degrades to
  "prefer the frames whose row ends are darkest".
- **`darkest` assumes bands only brighten.** A band adds light to what it covers, so the darkest
  sample of a pixel is usually the undistorted one — it scores best on banding of every method
  tried, and is the fastest. Two costs: a minimum over ten noisy samples is biased low and keeps
  the noise, so the result is darker (36–45 gray levels from `trimmed_mean`) and grainier; and a
  band that *darkens* is taken for the truth, which the tests pin down. `darkest_mean` trades a
  little of the band rejection for less bias and less noise.
- **Cost:** ~200 ms per 10-frame 1080p batch for `trimmed_mean` (`median` 320 ms, `consensus`
  440 ms, `darkest` 160 ms, `darkest_mean` 270 ms), against the seconds the batch already takes to
  decode.
- **Memory:** a `float32` stack of ten 1080p frames is 249 MB, which is why the per-pixel methods
  work in 256-row slices (~30 MB). The batch itself (~60 MB of `uint8` frames) is held only while
  its meme is processed.
- **PNG, not JPEG:** the point of cleaning is removing artefacts, so the result isn't re-compressed
  with a lossy codec that would ring around the residual band edges. This is a deliberate exception
  to "JPEG everywhere" (extraction-pipeline Q2); the batch frames stay JPEG.
- **`--classifier claude` is unaffected**: cleaning happens after classification and asks the
  classifier nothing.

## Open Questions

Resolved by the user (2026-09-17):

- Q1: Compare candidates first, or ship one method? **Compare first** on real batches, then make the
  winner the default.
- Q2: Where do cleaned images go? **`<run-name>/clean/meme_<n:03d>.png`**, their own folder.
- Q3: Crop to the card? **No** (see Out of Scope).
- Q4: On by default? **Yes**, with `--clean-method none` to turn it off.

Resolved during implementation:

- Q5: What does `run` return when cleaning is on? **The `clean/` paths** — that's the result the
  user wants and what the CLI prints. The batch frames stay on disk. With `clean_method=None` the
  batch frames are returned, as before.
- Q6: Which method is the default? **`clean_rows`**, chosen by the user after the whole video was
  processed with every method ([ADR 011](../../decisions/011-clean-rows-as-the-default.md)). It was
  `trimmed_mean` between the first comparison and that run.

## Changelog

- 2026-09-17: The user asked for each batch to be processed into one image with the distortion
  removed or reduced, noting that the static lines move vertically so the original colour of most
  pixels should be recoverable, and asked to evaluate simple options before anything complex.
  - Measured a real 1080p batch first (see Technical Notes): frames are aligned, the distortion is
    dense, and a consensus exists for about half the card — so a per-pixel temporal combination is
    worth trying and alignment is not needed.
  - The user chose: compare methods first, `clean/` folder, no cropping, on by default.
  - Added `batch_cleaner` with five candidates, the playground comparison entry points, the
    `clean_method` parameter and `--clean-method`, and the tests above. Ran the comparison on three
    real batches; `trimmed_mean` won on the banding score and by eye, and became the default.
  - Verified: `extract-memes sample/short.mp4` writes `clean/meme_001.png` and `clean/meme_002.png`
    with the dark band across the card gone. `pytest -m "not slow"` (119 passed) and
    `pytest -m slow` (5 passed).
- 2026-09-17: The user noticed that the static bands brighten the area they cover, and asked for a
  method that picks the darkest pixel per location. Added `darkest` (choose the frame where the
  pixel is darkest, by luminance, copying all three channels) and `darkest_mean` (average the
  darkest third, which keeps most of the band rejection with less of the minimum's darkening and
  noise). On the two real batches re-run, `darkest` has the best banding score of any method
  (1.12 and 0.68) and is the fastest, but shifts the whole image 36–45 gray levels darker than
  `trimmed_mean`. The default is unchanged pending the user's choice; the tests record that a band
  which darkens defeats `darkest`.
- 2026-09-17: The user reported that `darkest`/`darkest_mean` look best, and pointed out that the
  bands are not only bright but also colourful noise. Added `clean_rows`, which uses the
  letterbox bars: a row whose far ends aren't black is damaged in that frame, so only the rows
  whose ends are closest to black are averaged, with the least affected used where no row is clean.
  Measured 3.6 and 4.5 frames kept per row on the two real batches, with 15.4% / 0.1% of rows
  damaged in every frame. It's the fastest method, and cleans the margins visibly better than
  `trimmed_mean`. The default is still `trimmed_mean`, pending the user's choice.
- 2026-09-17: Ran the whole video end to end (`test_full_video_every_method`): 93 memes, 978
  full-quality frames, every batch cleaned with all eight methods into `.runtime/full_experiment/`.
  Medians across the 93 memes are in
  [ADR 011](../../decisions/011-clean-rows-as-the-default.md); the key finding is that `darkest`,
  `darkest_mean` and `clean_rows` bring the letterbox bars back to near-black (10-17 against 56-60
  for the averaging methods) while leaving the card's own content almost untouched (highlights
  207-210 against 217), and that `row_pick` is twice as banded as the raw input. The user chose
  **`clean_rows` as the default**. `tests/test_pipeline.py`'s "the result sits near the middle of
  the batch" assertion was replaced with "the result is less banded than the least banded frame it
  was made from": a row-selecting method legitimately sits further from the batch mean.
- 2026-09-17: The user asked to make saving the high-res frames optional. Added `save_high_res`
  (default `False`) and `--save-high-res` (AC13): a default run now writes only `clean/`, which for
  the hour-long video is 93 PNGs instead of those plus 978 full-quality JPEGs. Asking for neither
  the cleaned images nor the frames (`clean_method=None` without `save_high_res`) raises rather than
  running to produce nothing. Every test that inspects the batch folders now asks for them
  explicitly; `playground.test_full_video_every_method` passes `save_high_res=True`, since it
  cleans the batches afterwards.
