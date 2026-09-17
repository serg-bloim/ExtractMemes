# 011 — Clean Batches with `clean_rows` by Default

**Date:** 2026-09-17
**Status:** Accepted. Supersedes [ADR 010](010-batch-cleaning-by-trimmed-mean.md) Decision 1
(`trimmed_mean` as the default). Everything else in ADR 010 — the `clean/` layout, the return
value, cleaning on by default, no alignment — still holds.

---

## Context

ADR 010 chose `trimmed_mean` from a comparison of five methods on three batches. Two things changed
after it:

1. The user pointed out that the glitch bands **brighten** what they cover, which led to `darkest`
   (per pixel, the frame where it is darkest) and `darkest_mean` (the darkest third, averaged).
2. The user then pointed out that the distortion is not only bright bands but also **colourful
   noise bands**, and proposed judging each row of each frame by its ends: the source is
   letterboxed, so an undamaged row's far left and right are black, and any band lifts them. That
   is `clean_rows` — average the rows whose ends are closest to black, falling back to the least
   affected rows where every frame is damaged.

The whole video was then processed end to end: 93 memes, 978 full-quality frames, every batch
cleaned with all eight methods (`.runtime/full_experiment/`). Medians across the 93 memes:

| Method | Banding | vs best input frame | Margin brightness | Card highlights |
|---|---|---|---|---|
| best input frame | 1.56 | — | — | — |
| best_single | 1.56 | 0% | 59.5 | 252 |
| median | 1.35 | −13% | 56.5 | 219 |
| trimmed_mean | 1.15 | −26% | 60.0 | 217 |
| consensus | 1.36 | −13% | 56.3 | 219 |
| row_pick | 3.16 | +103% | 56.3 | 228 |
| darkest | **1.05** | −33% | 9.8 | 207 |
| darkest_mean | 1.08 | −31% | 14.5 | 208 |
| **clean_rows** | 1.28 | −18% | 17.4 | 210 |

The margin column is the letterbox bars: `darkest`, `darkest_mean` and `clean_rows` bring them back
to near-black (10–17) instead of the 56–60 the averaging methods leave, which is why they look so
much cleaner. The card's own content is nearly unaffected (highlights 207–210 against 217).

The user judged `darkest`/`darkest_mean` best by eye, then chose `clean_rows` as the default after
seeing the full set.

## Decision

**`DEFAULT_METHOD = "clean_rows"`.** Every other method stays available through `--clean-method`.

Why `clean_rows` over the darkest-pixel methods, which score slightly better on banding:

- It is the only method that detects damage instead of assuming a direction. `darkest` treats a
  band that *darkens* as the truth; `clean_rows` reads the letterbox bars, which any band lifts,
  whether it is bright or colourful noise.
- It averages several clean rows, so it also suppresses grain. A per-pixel minimum is biased low
  and keeps the noise of whichever sample it picked.
- It is the fastest method measured (64 ms per 10-frame 1080p batch, against 191 ms for
  `trimmed_mean`), because it only ever looks at the row ends.
- It degrades gracefully: where no row is clean — 15.4% of rows in one measured batch — it averages
  the least affected rows rather than producing nothing.

## Consequences

**Positive:**
- Both kinds of band are removed, and the static in the margins goes nearly black.
- Cheapest method in the set, so cleaning stays negligible against decoding.

**Negative / costs:**
- **It assumes a letterboxed source.** Without black bars the detector reads card content, and the
  method degrades to preferring the frames whose row ends are darkest. A source that fills the
  frame needs a different default; this is the main thing to re-check on new material.
- **Slightly higher banding than `darkest`** (1.28 vs 1.05 median), traded for correct handling of
  dark bands and less noise.
- **It selects, so the result mixes rows from different frames.** No seam was visible on the 93
  memes, but a card that moves within a batch would produce one.
- Runs made before this change used `trimmed_mean`; their `clean/` images are not regenerated.

## References

- [ADR 010](010-batch-cleaning-by-trimmed-mean.md) — the superseded default and the original
  five-method comparison.
- [batch-cleaning](../specs/features/batch-cleaning.md) — the spec, with each method's computation.
- `.runtime/full_experiment/` — 93 memes × 8 methods, the evidence for this decision.
