# 005 — Checkpoint: Runtime Layout, 2fps Default, Meme-Reveal Prompt

**Date:** 2026-09-16
**Status:** Accepted. File naming inside `frames/` and `saved/` changed later: JPEG only, a
6-digit frame index in every name, and scan-quality `thumb_frame_*` previews in `saved/`. See the
extraction-pipeline spec. The prompt in decision 3 was replaced by the user's rubric; see the
meme-classifier spec.

---

## Context

The first real end-to-end run (documented in ADR 004 and the four M1–M4 specs) used `/tmp`
paths for downloads/output as a one-off smoke-test convenience, and wrote scan-pass frames to a
`tempfile.TemporaryDirectory` that was deleted as soon as scanning finished. Looking at that
run's actual output (`frame_20.00s.png`, `frame_24.00s.png` — a presenter with a small inset
thumbnail, not a real meme) showed the classifier prompt was too broad: it was matching "any
frame with a captioned/reaction-looking image somewhere in it" rather than the specific visual
pattern this video actually uses for meme reveals — a meme image centered in the frame against a
dark background, with the whole frame covered in analog-TV-style static/noise, distinct from the
ordinary presenter shots.

This is the checkpoint ADR 002's M5 anticipated ("with real output in hand, confirm or adjust
the sampling rate"), arriving from the user's direct review of the first run's output rather than
from a separate scheduled step.

## Decision

1. **Runtime file layout moves into the project, under `.runtime/`.** All per-run artifacts
   that ADR 004 introduced now live at `.runtime/<run-name>/{frames,saved}/`:
   - `frames/` — every sampled frame from the scan pass, kept (previously written to a
     temp dir and deleted once scanning finished).
   - `saved/` — the final full-quality meme images extracted at flagged timestamps
     (previously `output/`).
   `downloads/` (the two quality-tier video downloads from ADR 004) is unchanged — it already
   lived in the project root, gitignored.
   `<run-name>` defaults to a slug derived from `source` (local file stem, or URL's last path
   segment) so multiple videos don't collide; overridable with `--run-name`.
2. **Default scan rate is now 2fps**, up from 1fps.
3. **Classifier prompt now names the specific meme-reveal pattern**: a meme image centered in
   the frame, dark/black background around it, analog TV-static/noise over the whole frame —
   instead of the more generic "is this a meme image" question from ADR 004.

## Options Considered

### Option A: Keep tuning the generic prompt with more examples/wording

Rejected: the user already knows the exact visual signature memes take in this specific video
(dark background, centered image, static overlay) — encoding that directly is more reliable than
iterating on a generic "is this a meme" prompt.

### Option B: Keep scan frames in a temp dir, only expose a `--keep-frames` flag

Rejected: the user wants to routinely inspect scan frames while tuning the classifier prompt
further, so keeping them is the default, not an opt-in flag — matches the current tuning-heavy
phase of the project.

## Consequences

**Positive:**
- Every artifact from a run is inspectable after the fact, in the project directory, without
  digging through `/tmp`.
- The classifier prompt now matches this project's actual meme-reveal visual pattern, which
  should sharply reduce false positives like the presenter-with-inset frames from the first run.

**Negative / costs:**
- `frames/` grows one file per sampled frame per run (at 2fps, ~157 files for a 78s video) and is
  never cleaned up automatically — acceptable for now (a solo, tuning-focused project), revisit if
  disk usage becomes a problem.
- Doubling the scan rate to 2fps roughly doubles classification API calls (and cost/time) for the
  scan pass.

## References

- `decisions/004-claude-classifier-and-dual-resolution-download.md`
- `specs/features/extraction-pipeline.md`
- `specs/features/meme-classifier.md`
- `specs/features/frame-extraction.md`
