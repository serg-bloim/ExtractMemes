# 002 — Meme Extraction Pipeline: Walking-Skeleton Rollout Plan

**Date:** 2026-09-16
**Status:** Accepted

---

## Context

The project goal is to extract meme images from YouTube videos. The overall pipeline is
well-defined (download → extract frames → classify → save), but significant questions remain,
most importantly **which classification approach to use**. The project itself is still just a
PyCharm-generated `main.py` stub — no dependencies, no module structure, nothing runs.

Before writing any code, we needed to decide: what gets built first, and does the classifier
decision (the least understood, highest-uncertainty part) need to be made up front, or can it
be deferred? Deciding it up front risks locking in an approach with no real extracted frames
to evaluate it against.

---

## Decision

Build the pipeline as a **walking skeleton**: get download → extract → save fully working
end-to-end first, with classification implemented behind a small stub interface
(`FrameClassifier.is_meme(frame) -> bool`) that does no real ML work. Defer the real classifier
decision to its own milestone (M6), made once real extracted frames exist to evaluate
candidate approaches against.

Milestones, in order:

1. **M0 — Project setup**: `requirements.txt`, package layout (`extract_memes/` with
   `downloader.py`, `frame_extractor.py`, `classifier.py`, `pipeline.py`, plus `main.py` as CLI
   entrypoint), `.gitignore` updates, fill in CLAUDE.md's Code Conventions section.
2. **M1 — Video download**: `yt-dlp` downloads a YouTube URL to a local file.
3. **M2 — Frame extraction**: `opencv-python` (`cv2.VideoCapture`, bundled FFmpeg backend —
   no separate system `ffmpeg` install needed) samples frames at a default of 1 fps.
4. **M3 — Classifier interface (stub only)**: the `FrameClassifier` interface, with a stub
   implementation (e.g. always-true, or an interactive y/n prompt) — no ML yet.
5. **M4 — Save output + CLI wiring**: orchestrate M1→M2→M3, write flagged frames to an output
   directory, expose it all via `python main.py <youtube_url>`. First fully runnable milestone.
6. **M5 — Spec checkpoint**: with real output in hand, resolve Q3 (sampling rate) and decide
   Q2 (dedup) or explicitly defer it; update the spec's acceptance criteria.
7. **M6 — Real classifier**: pick the classification approach using real sample
   frames as evaluation data; replace the M3 stub behind the same interface. Gets its own ADR and spec.
8. **M7 — Dedup** (if deferred from M5): near-duplicate frame suppression, e.g. perceptual
   hashing via `imagehash`.

Dev process: solo project on `main`, no CI for now. Validate each milestone by actually running
it against one real short YouTube video rather than mocking/unit-testing the early I/O-heavy
milestones; add unit tests once there's pure logic worth isolating (e.g. M7's hashing). Spec
status stays `draft` through M0–M4 (an explicit prototype spike, per CLAUDE.md's prototyping
exception to "spec before code"), moves to `ready` at the M5 checkpoint, and to `implemented`
only once the real classifier (M6) meets every acceptance criterion.

---

## Options Considered

### Option A: Decide the classifier approach up front, build top-down

Resolve the classifier approach first (pick vision-LLM vs. local CLIP vs. heuristic), then build the full
pipeline against that decision.

**Rejected:** Locks in the highest-uncertainty decision before there's any real data (actual
extracted frames from an actual video) to evaluate it against. Risks committing to an approach
that turns out to be a poor fit once real output is visible.

### Option B: Walking skeleton, classifier stubbed and deferred (chosen)

Build the mechanical pipeline first with a stubbed classifier interface; decide the real
classifier later, against real data.

**Chosen because:** Produces a runnable tool almost immediately, de-risks the parts we already
understand well (download, frame extraction, file I/O), and turns the classifier choice into an
informed decision instead of an upfront guess — matching the user's request to see "the overall
picture" before committing to classifier implementation details.

### Option C: Build all pipeline stages in isolation, integrate at the end

Fully build and unit-test each stage independently, wire them together only once everything is
individually "done."

**Rejected:** Delays having any runnable end-to-end tool until every stage is finished, and
early stages (download, extraction) are thin wrappers around `yt-dlp`/`opencv` best validated
by an actual run rather than in isolation.

---

## Consequences

**Positive:**
- A runnable tool exists after M4, well before the hardest decision (classifier) is made.
- The classifier decision (M6) gets made with real evaluation data instead of speculation.
- Each milestone is independently useful and independently verifiable by running it.

**Negative / costs:**
- The stub classifier in M3–M5 means early runs "save everything," which is not the real
  feature — this is intentional scaffolding, not a shortcut on the final acceptance criteria.
- Milestones M0–M4 are built without prior specs (a deliberate, explicit exception to the normal
  spec-before-code rule), justified by CLAUDE.md's own prototyping allowance. Specs for
  individual milestones are written as each becomes `ready` to implement.

---

## References

- `CLAUDE.md` — Project Overview (pipeline description), "What Claude Should Never Do" (prototyping exception)