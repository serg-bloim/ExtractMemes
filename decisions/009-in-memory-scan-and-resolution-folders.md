# 009 — Iteration 3: Scan Frames in Memory; Separate, Opt-In Low-Res Output

**Date:** 2026-09-17
**Status:** Proposed. Supersedes, once accepted, two parts of
[ADR 005](005-runtime-layout-and-classifier-checkpoint.md) Decision 1: keeping every sampled frame
in `frames/`, and the `saved/` folder.

---

## Context

[ADR 005](005-runtime-layout-and-classifier-checkpoint.md) made every run keep all its sampled
frames in `.runtime/<run-name>/frames/`, and it rejected a `--keep-frames` flag (Option B). The
reason was the tuning phase: the user routinely inspected scan frames while refining the Claude
prompt. Later, `saved/` also got a scan-quality `thumb_frame_*` copy of each meme next to its
best-quality `frame_*` copy (ADR 007 register 37). The copy gave feedback during scans that took
hours with Claude.

[ADR 008](008-heuristic-classifier-iteration.md) changed both reasons:

- The heuristic classifier is the default, deterministic, and calibrated. Its labeled set lives in
  `data/labeled_dataset/`, so tuning no longer needs every run's frames.
- A heuristic scan of the 1-hour `sample/full.mp4` takes seconds. Live thumbnails aren't needed to
  see progress.
- With the heuristic, the remaining per-frame cost is encoding a JPEG for each sample and reading
  it back so the classifier gets a file. Without those writes, scanning `full.mp4` (7842 samples)
  took ~7 s in total.

The user asked for two changes:

1. Keep scan frames in memory by default. An option writes them to `frames/`, for inspection.
2. Put low-res and high-res memes in separate folders, and produce low-res memes only when an
   option asks for them.

## Decision

1. **Scan frames stay in memory by default.** `pipeline.run(save_frames=False)` and the CLI flag
   `--save-frames` write them to `<run-name>/frames/` with the existing names. See the
   [in-memory-frames spec](../specs/features/in-memory-frames.md).
2. **The pipeline classifies arrays, not files.** `FrameClassifier` gets a concrete
   `is_meme_frame(frame)`:
   - By default it writes the frame to a temporary file, calls `is_meme(path)`, and deletes the
     file. That's how `ClaudeCliClassifier` keeps working unchanged, since the `claude` CLI can
     only read files.
   - `HeuristicClassifier` already overrides `is_meme_frame` and never touches disk.
   - The verdict doesn't depend on `--save-frames`.
3. **Output folders by resolution, directly in the run folder.** `<run-name>/high-res/` holds the
   best-quality memes (always produced). `<run-name>/low-res/` holds the scan-quality copies, which
   are written only with `save_low_res=True` / `--save-low-res`. `saved/` is no longer used. A
   meme has the same file name in both folders, with no `thumb_` prefix. See the
   [resolution-output-folders spec](../specs/features/resolution-output-folders.md).
4. **Both specs are iteration specs** (ADR 008 Decision 4). The baseline specs and the
   heuristic-classifier spec stay unchanged, and each new spec lists what it amends.
5. **Rebuild order is extended.** After iteration 2 (the heuristic classifier), apply
   `in-memory-frames` and then `resolution-output-folders`.

## Options Considered

### Frames

- **Keep writing every frame by default (ADR 005 as is).** Rejected by the user: frames were only
  needed for inspection, and the reason for keeping them by default (prompt tuning) is gone.
- **Drop frame writing entirely, with no option.** Rejected: inspecting a new source's frames is
  still how a threshold problem would be diagnosed (heuristic-classifier Technical Notes,
  calibration scope).
- **Opt-in `--save-frames` (chosen).**

### How the Claude classifier gets a file when frames stay in memory

- **A temporary file per frame, deleted after classification (chosen by the user).** Nothing
  stays on disk whichever classifier is used, and `classifier.py`'s CLI contract is unchanged.
  The extra JPEG write is negligible next to an 8–16 s Claude call.
- **`--classifier claude` forces frame saving.** Rejected: the choice of classifier would quietly
  change what's left on disk.
- **Reject `--classifier claude` without `--save-frames`.** Rejected: it adds a rule the user must
  remember, only to work around how the classifier gets its input.

### Output layout

- **`high-res/` and `low-res/` directly in the run folder, next to `frames/` (chosen by the user).**
  The run folder stays flat: one folder per kind of image.
- **`saved/high-res/` and `saved/low-res/`.** Rejected by the user.
- **Keep one folder and tell resolutions apart by the `thumb_` prefix (status quo).** Rejected by
  the user.

## Consequences

**Positive:**
- A default run writes only the memes, so a heuristic scan does no per-frame disk I/O.
- A default run folder holds just `high-res/`, so there's nothing to sort through or clean up.
- Low-res and high-res copies of a meme pair up by identical file name.

**Negative / costs:**
- **The heuristic now sees raw decoded frames instead of JPEG-decoded ones.** Measured while
  drafting (2026-09-17): the flagged samples are identical on `short.mp4` (2) and `full.mp4` (93),
  but texture scores shift by up to 9.7. See the in-memory-frames spec's Technical Notes.
- **No live feedback by default.** A long Claude scan shows nothing until it ends, unless
  `--save-low-res` is given.
- **Old runs keep the old layout.** Existing `.runtime/*/saved/` folders aren't migrated or
  removed.
- **Reading the docs gets harder again:** current pipeline behavior is the extraction-pipeline spec
  as amended by the heuristic-classifier spec and then by these two specs.
- **CLAUDE.md needs updating when the specs are implemented:**
  - the Project Overview: step 2 ("save each one", "saved right away as scan-quality thumbnails")
    and step 4 (`saved/`);
  - the Directory Structure `.runtime/` block (`frames/` only with `--save-frames`, `high-res/`,
    `low-res/`).
- **ADR 005 and the ADR index** get their status updated to point here when this ADR is accepted.

## Issue Register (continued from ADR 008)

**State values:** as in ADR 008, plus **Iteration 3**: resolved by the in-memory-frames or
resolution-output-folders spec once implemented.

| # | Issue / question | Resolution | State | Where |
|---|---|---|---|---|
| 64 | Every sampled frame is written to `frames/` and read back only so the classifier gets a file; the frames were needed only for inspection. | Classify in memory; `--save-frames` writes them on request. | Iteration 3 | in-memory-frames AC2–AC5 |
| 65 | `ClaudeCliClassifier` can only classify a file on disk. | `FrameClassifier.is_meme_frame` defaults to a temporary-file round trip. | Iteration 3 | in-memory-frames AC1 |
| 66 | Scan-quality `thumb_frame_*` and best-quality `frame_*` files are mixed in `saved/`, and the thumbnails are always written. | `high-res/` and `low-res/` folders with identical names; low-res only with `--save-low-res`. | Iteration 3 | resolution-output-folders AC1–AC6 |
| 67 | Commit `8651a9e` inserted `test_default_run_finds_exactly_the_known_memes` between `@pytest.mark.slow` and `test_real_url_run`. The real-network test now runs in `pytest -m "not slow"`, and the offline end-to-end check (heuristic-classifier AC11) runs only with `-m slow`. | Regression: move the decorator back onto `test_real_url_run`. No spec change. Fixed in commit `44add50`. | Resolved | `tests/test_pipeline.py` |

## References

- [in-memory-frames](../specs/features/in-memory-frames.md) and
  [resolution-output-folders](../specs/features/resolution-output-folders.md): the iteration specs
  for this decision.
- [ADR 005](005-runtime-layout-and-classifier-checkpoint.md): the frames-kept layout this
  supersedes.
- [ADR 008](008-heuristic-classifier-iteration.md): the iteration-spec convention and the
  heuristic classifier.
- [ADR 007](007-documentation-consolidation-for-rebuild.md): rebuild order and register item 37.
- [extraction-pipeline](../specs/features/extraction-pipeline.md),
  [meme-classifier](../specs/features/meme-classifier.md),
  [heuristic-classifier](../specs/features/heuristic-classifier.md),
  [dev-harness](../specs/features/dev-harness.md): the specs these iterations amend.
