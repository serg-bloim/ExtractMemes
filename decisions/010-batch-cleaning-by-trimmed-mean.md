# 010 — Clean Each Meme Batch with a Temporal Trimmed Mean

**Date:** 2026-09-17
**Status:** Accepted; Decision 1 (the default method) superseded by
[ADR 011](011-clean-rows-as-the-default.md), which makes `clean_rows` the default. The rest of this
decision stands.

---

## Context

A meme is now extracted as a batch of the ~10 consecutive full-quality frames the card is on screen
for (`high-res/meme_<n:03d>/`). Every one of them is crossed by VHS-style glitch bands that sit over
the card, and no frame is free of them, so shipping "the" frame means shipping its damage.

The user asked for the batch to be reduced to one image with the distortion removed or reduced —
explicitly accepting an imperfect result — and observed that the bands move vertically between
frames, so the original colour of most pixels should be recoverable. They asked to evaluate simple
options before any complex analysis.

Measurements on a real 10-frame 1080p batch (99.56 s of `0TSqnhLXYfA`, the source of
`sample/full.mp4`), 2026-09-17:

- **The frames are geometrically stable.** A ±25 px vertical shift search picks `dy=0` for every
  frame, and phase correlation gives < 0.05 px. Registration, the expensive part of any
  multi-frame restoration, is unnecessary.
- **A consensus exists for about half the card.** 55.4% of card pixels have 5 of 10 frames agreeing
  within 6 gray levels (48.3% for 6 of 10).
- **The distortion is dense, not sparse.** Each frame differs from the batch's trimmed mean by
  26–36 gray levels on average; per-pixel temporal std in the card area is 36.9. So a composite
  cannot be perfect, which matches what the user asked for.
- **Brightness drifts** across a batch (card mean 103.1 → 108.1), so combining without normalising
  would bias the result toward the darker frames.

## Decision

1. **Clean each batch with a per-pixel temporal trimmed mean**, after aligning the frames'
   brightness: sort the stack per pixel, drop the `max(1, N // 5)` extremes at each end, average
   the rest. This is `DEFAULT_METHOD` in the new `batch_cleaner` module.
2. **Do not align frames.** Measured unnecessary (above).
3. **Keep the losing candidates in the module** (`best_single`, `median`, `consensus`, `row_pick`)
   behind `--clean-method`, because the winner was chosen by eye on three batches from one show,
   and another source may favour a different one.
4. **One cleaned PNG per meme in `<run-name>/clean/`**, and `run` returns those paths. The batch
   frames stay on disk as the evidence.
5. **Cleaning is on by default**, at ~200 ms per batch.

## Options Considered

Each was implemented and run on three real batches; `banding_score` is the roughness of the card's
row-brightness profile, which a band spikes (lower is less banded):

| Method | 99.56 s | 687.36 s | 2812.32 s | Verdict |
|---|---|---|---|---|
| `best_single` (least-banded input frame) | 1.58 | 1.40 | 1.11 | **Rejected.** The control. Keeps a wide bright band straight across the card — the worst result by far, and the one the pipeline produced before. |
| `median` | 1.36 | 1.24 | 0.80 | Rejected, narrowly. Removes the bands as well as the trimmed mean but keeps more chroma speckle: with ten frames it interpolates two samples instead of averaging six. |
| **`trimmed_mean`** | **1.16** | **1.07** | **0.74** | **Chosen.** Best banding score on every batch, and by eye the cleanest, with the card's text still sharp. |
| `consensus` (average the frames that agree, median elsewhere) | 1.36 | 1.24 | 0.81 | Rejected. This is the user's intuition implemented literally, but it scores like the median and is twice as slow: where no consensus exists it *is* the median, and that is where the damage is. |
| `row_pick` (per row, copy the least-deviating frame's row) | 3.17 | 2.80 | 1.41 | Rejected. Keeps full sharpness in theory, but the rows come from different frames and the seams between them are worse than the bands. |

Added after the comparison, at the user's suggestion that the bands brighten what they cover:

| Method | 99.56 s | 2812.32 s | Verdict |
|---|---|---|---|
| `darkest` (per pixel, the frame where it is darkest, chosen by luminance) | **1.12** | **0.68** | Best banding score of any method, and the fastest (160 ms). Not made the default yet: it shifts the whole image 36–45 gray levels darker than `trimmed_mean`, because a minimum over ten noisy samples is biased low and keeps the noise, and a band that *darkens* is taken for the truth. |
| `darkest_mean` (average the darkest third) | 1.14 | 0.69 | Nearly the same band rejection with less of that bias and noise. |
| `clean_rows` (average the rows whose ends are closest to black) | 1.34 | 0.94 | Uses the letterbox bars as a damage detector, so it catches colourful noise bands as well as bright ones, at normal brightness and in a third of the time. Keeps 3.6 / 4.5 frames per row on average; 15.4% / 0.1% of rows are damaged in every frame and fall back to the least affected. |

Also considered and not built: aligning frames before combining (unnecessary, above), and cropping
the cleaned image to the card (the user chose to keep the full frame; finding the card's edges is
its own problem).

## Consequences

**Positive:**
- The delivered image is dramatically better than any single frame: the bands crossing the card are
  gone, and the card's text is readable.
- No new dependency, no alignment, ~200 ms per batch — negligible next to decoding.
- The batch frames remain, so a different method can be tried on an existing run's output.

**Negative / costs:**
- **The result is an average, not a real frame.** Where the distortion is dense in most frames, it
  softens rather than removes; and no pixel is guaranteed authentic.
- **The static margins stay** — they're noise in every frame, so combining only smooths them.
- **The banding score ranks `darkest` first, but it also darkens the image** — the score measures
  banding only. The user judged `darkest`/`darkest_mean` best by eye, so the default may yet change.
- **`clean_rows` assumes the source is letterboxed.** On a source without black bars its detector
  reads card content instead, and it degrades to preferring the darkest-edged rows.
- **Chosen by eye, on three batches from one show.** Another source (different glitch style, a card
  that moves, fewer frames per card) may need a different method; that's why the others stay.
- **Memory:** a `float32` stack of ten 1080p frames is 249 MB, so the per-pixel methods work in
  256-row slices.
- **PNG output** breaks the project's "JPEG everywhere" rule (extraction-pipeline Q2), deliberately:
  re-compressing a de-artefacted image would ring around what's left of the bands.
- **`run`'s return value changed** from batch frames to cleaned images when cleaning is on.

## Issue Register (continued from ADR 009)

**State values:** as in ADR 009, plus **Iteration 4**: resolved by the batch-cleaning spec.

| # | Issue / question | Resolution | State | Where |
|---|---|---|---|---|
| 68 | A meme was delivered as ~10 frames, every one of them banded; picking one kept its damage. | Combine the batch with a temporal trimmed mean into `clean/meme_<n>.png`. | Iteration 4 | batch-cleaning AC1–AC9 |
| 69 | Whether multi-frame cleaning needs registration was unknown. | Measured: `dy=0` for every frame, phase correlation < 0.05 px. No alignment. | Resolved | batch-cleaning Out of Scope |
| 70 | The static margins are noise in every frame, so no temporal method can recover them. | Accepted; cropping to the card is a separate future feature. | Open | batch-cleaning Out of Scope |
| 71 | The default was chosen by eye on three batches from one show. | Keep every candidate behind `--clean-method`; revisit on a new source. | Open | this ADR, Consequences |

## References

- [batch-cleaning](../specs/features/batch-cleaning.md) — the spec for this decision.
- [extraction-pipeline](../specs/features/extraction-pipeline.md) — the batch extraction this
  builds on; its "refining a batch into one resulting image" out-of-scope item is now done.
- [ADR 008](008-heuristic-classifier-iteration.md) — the iteration-spec convention, and the
  measurement that a card is on screen for exactly 10 frames.
- `.runtime/_playground/clean/real_*/sheet.png` — the comparison images the decision was made from.
