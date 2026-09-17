# 008 — Iteration 2: Classify with a Hand-Built Image Heuristic; Keep the Claude Classifier as the Baseline

**Date:** 2026-09-16
**Status:** Accepted

---

## Context

The Claude CLI classifier ([ADR 004](004-claude-classifier-and-dual-resolution-download.md),
[meme-classifier spec](../specs/features/meme-classifier.md)) works: the rebuild smoke check
flagged exactly the two glitch cards in `sample/short.mp4`. But it takes about 8–16 s per sampled
frame. `sample/short.mp4` (164 samples) took 22 minutes, and `sample/full.mp4` (7842 samples) would
take about 17 hours. [ADR 007](007-documentation-consolidation-for-rebuild.md) left this open as
register item 32.

The user observed that the meme cards in these videos look very distinctive and asked whether plain
image analysis could replace Claude. Before this ADR, that was measured on the existing material:

- **Labeled set** (15 positive, 23 negative, 256x144 PNG): then in `.runtime/experiment/`, since
  moved to `data/labeled_dataset/` (register 63).
- **`sample/short.mp4`:** the 164 scan JPEGs from the rebuild smoke run.
- **`sample/full.mp4`:** the 7842 scan JPEGs in `.runtime/full/frames/`.

Two measurements, both taken only in the left and right fifths of the frame (outside the card),
separate the classes:

- **Band score:** the brightest row's mean brightness minus the median row brightness. A white
  glitch band crossing dark static scores ≥ 218. No other frame in the 7842 samples of `full.mp4`
  scores above 144, and no labeled negative above 123.
- **Texture score:** the mean change in HSV saturation between vertically adjacent pixels.
  Multicolored static scores 23–32. Blur, pillarbox bars, and flat backgrounds score low. Busy
  presenter shots with QR codes or posters also reach ~32, so this score only works as a guard
  alongside the band score, never alone.

The rule `band > 180 and texture > 18`:

- classifies all 38 labeled frames correctly;
- flags exactly 10.56 s and 28.80 s in `short.mp4`, the same result as the Claude classifier;
- flags 93 samples (92 distinct cards) in `full.mp4`, all visually confirmed as glitch-framed cards;
- runs in about 0.5 ms per frame, including reading the JPEG (7842 frames in 3.7 s).

The same investigation found an independent problem with sampling. Each glitch card is on screen
for exactly 10 frames (0.40 s at 25 fps; measured by decoding every frame around six known cards).
The default "2 fps" sampling takes every 12th frame (0.48 s). A card whose 10 frames fall between
two samples is never classified at all: 5 of the 15 labeled positives (1:17, 2:36, 2:53, 6:07, 7:49)
appear in none of `full.mp4`'s samples.

The user wants this as a **new iteration**, not an edit of the existing classifier docs. If the
project is ever recreated, the rebuild should still start with the simpler Claude classifier.

## Decision

1. **Add `HeuristicClassifier` as a second `FrameClassifier` implementation**, in its own module
   `src/extract_memes/heuristic_classifier.py`. It computes the band and texture scores exactly as
   defined in the [heuristic-classifier spec](../specs/features/heuristic-classifier.md). It needs
   no new dependency: OpenCV and NumPy are already declared.
2. **Keep `ClaudeCliClassifier` unchanged and selectable.** The meme-classifier spec, its verbatim
   prompt, `classifier.py`, and ADR 004 are not modified.
3. **Make the heuristic the default** for `pipeline.run` and the `extract-memes` CLI, with a
   `--classifier {heuristic,claude}` switch. (Proposed; confirmation pending in the spec's Q1.)
4. **Iteration specs.** An iteration is a new spec layered on top of already-implemented specs:
   - Earlier specs stay unchanged as the **baseline**. They describe iteration 1 and are what a
     rebuild implements first.
   - The iteration spec lists every earlier acceptance criterion it amends in an **Amends**
     section, and its own acceptance criteria describe the amended behavior.
   - Where an iteration spec and a baseline spec disagree, the iteration spec wins once it is
     `implemented`.
5. **Rebuild order is extended, not replaced.** A rebuild follows ADR 007 steps 1–6 and its smoke
   check with the Claude classifier. Then it applies the iteration specs in ADR order, starting
   with this one.
6. **The sampling gap is not fixed in this iteration.** Scanning more often reverses a deliberate
   decision (frame-extraction Q3). It also multiplies the JPEG writes to `frames/` and makes
   duplicate hits of the same card certain (register item 44). It gets its own later iteration.
   This one only changes how a frame is judged.

## Options Considered

### Option A: Keep Claude and make it faster

Batch several frames per call, run calls in parallel, trim per-call session overhead (register
item 33), or call the API directly.

**Rejected:** even an optimistic 10x speedup leaves `full.mp4` at hours, still costs usage per
frame, and still needs `claude` installed. It also doesn't make denser sampling affordable.

### Option B: Hand-built image heuristic (chosen)

**Chosen:** two scores already separate the classes with a wide margin on all available material.
It's deterministic, needs no dependency, and runs about 10,000x faster.

### Option C: Train a model (CLIP embeddings plus a linear classifier, or a small CNN)

**Rejected for now:** it adds heavy dependencies (e.g. `torch`), needs a larger labeled set, and
isn't needed while two scores separate the classes this cleanly. Reconsider if videos with other
glitch styles break the heuristic. The heuristic and Claude could label training data then.

### Option D: Heuristic pre-filter, Claude verifies the hits

**Rejected as the default:** every one of the 93 heuristic hits in `full.mp4` was already a real
card, so verification would add `claude` back as a dependency without a measured benefit. It can be
a later iteration if false positives show up on new sources.

### Option E: Rewrite the meme-classifier spec in place

**Rejected by the user:** a recreated project should still start with the simpler Claude
classifier, so its spec stays the baseline.

## Consequences

**Positive:**
- Classification stops dominating runtime; decoding and JPEG writes do.
- It's deterministic, so tests can assert exact results (e.g. exactly two memes in `short.mp4`)
  instead of the smoke-check-only validation the Claude classifier allows.
- The offline test suite can exercise the real default classifier end to end.
- It makes the sampling-gap fix affordable.

**Negative / costs:**
- **Calibrated on one show's format**, from 256x144 scan frames. A different glitch style,
  resolution, or band color can make it miss cards silently. There's no "explanation" to inspect,
  only two numbers. The playground entry point in the spec exists to re-check the labeled set
  after any change.
- **Two classifiers to maintain**, and two defaults to keep straight in docs.
- **Reading the docs gets harder:** the current behavior of the pipeline and CLI is the
  extraction-pipeline spec as amended by the heuristic-classifier spec.
- **CLAUDE.md needs updating when this is accepted:**
  - the Project Overview (step 2 names Claude);
  - the Directory Structure (the new module);
  - the iteration-spec convention from Decision 4. The rule "never make breaking changes to
    existing implemented features without updating the relevant spec" should read "…without
    updating the relevant spec or writing an iteration spec that amends it."

## Issue Register (continued from ADR 007)

**State values:** as in ADR 007, plus **Iteration 2**: resolved by the heuristic-classifier spec
once it's implemented.

| # | Issue / question | Resolution | State | Where |
|---|---|---|---|---|
| 57 | Register 32: Claude takes ~8–16 s per frame, so a 1-hour video takes ~17 h. | `HeuristicClassifier`, ~0.5 ms per frame, default classifier. | Iteration 2 | heuristic-classifier AC1–AC6 |
| 58 | 2 fps sampling (every 12th frame) skips cards that are shown for 10 frames; 5 of 15 labeled positives were never sampled. | Scan at most every 10th frame (every 5th gives two hits per card). Needs its own spec: it reverses frame-extraction Q3 and multiplies `frames/` writes. | Open | this ADR, Decision 6 |
| 59 | With denser sampling, one card is flagged several times (register 44 becomes certain). | Merge back-to-back hits into one meme; address together with 58. | Open | this ADR, Decision 6 |
| 60 | The texture score alone doesn't separate cards from busy presenter shots (both reach ~32). | Used only as a guard next to the band score. | Documented | heuristic-classifier Technical Notes |
| 61 | A first rule also required a bright row across ≥ 85% of the frame width; it missed 4 real cards where the card interrupts the band. | Condition dropped. | Resolved | heuristic-classifier Technical Notes |
| 62 | Thresholds are calibrated on 256x144 frames from one show's format. | Documented limit. Re-check the labeled set with the playground entry point before trusting new sources. | Documented | heuristic-classifier Technical Notes, AC7 |
| 63 | Register 40: the labeled set lives in disposable `.runtime/experiment/`, and tests now need it. | Moved to `data/labeled_dataset/{positive,negative}/` (user decision, 2026-09-16). Baseline docs that still name `.runtime/experiment/` (meme-classifier Technical Notes, ADR 007) refer to this location. | Resolved | heuristic-classifier Q2 |

## References

- [heuristic-classifier spec](../specs/features/heuristic-classifier.md): the iteration spec for
  this decision.
- [ADR 004](004-claude-classifier-and-dual-resolution-download.md): the Claude classifier this
  iteration keeps as the baseline.
- [ADR 007](007-documentation-consolidation-for-rebuild.md): rebuild order and register items 32,
  33, 40, and 44.
- [meme-classifier](../specs/features/meme-classifier.md),
  [extraction-pipeline](../specs/features/extraction-pipeline.md),
  [frame-extraction](../specs/features/frame-extraction.md),
  [dev-harness](../specs/features/dev-harness.md): the baseline specs.
