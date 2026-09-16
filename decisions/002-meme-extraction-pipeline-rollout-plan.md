# 002 — Meme Extraction Pipeline: Walking-Skeleton Rollout Plan

**Date:** 2026-09-16
**Status:** Partially superseded by [004](004-claude-classifier-and-dual-resolution-download.md) —
M1, M3, M4, and M6 were folded into one Claude-based classifier + dual-resolution download design.
M0, M5, and M7 are unaffected. M2's 1 fps default was raised to 2 fps by
[005](005-runtime-layout-and-classifier-checkpoint.md), and M2 uses `opencv-python-headless`
instead of `opencv-python`. The "no system `ffmpeg`" goal still holds for frame reading, but
downloads now use ffmpeg bundled via `static-ffmpeg` — see
[006](006-youtube-video-only-formats-and-download-toolchain.md). M4's `output/` directory was
replaced by `.runtime/<run-name>/` in 005.

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

1. **M0 — Project setup**: a `src/` layout with the package at `src/extract_memes/`. All
   dependencies are declared in `pyproject.toml` (dev tools in a `dev` optional group; no
   `requirements.txt`), installed with `pip install -e ".[dev]"`. The tool runs as an
   `extract-memes` console command or `python -m extract_memes`, with no root `main.py`. Tests
   live in a top-level `tests/` folder and run with pytest. A `.gitignore` covers `.venv/`,
   `.idea/`, Python and pytest caches, build metadata, `downloads/`, and `output/`. Fill in
   CLAUDE.md's Code Conventions and Directory Structure sections. Python 3.14 only. M0 creates
   only the package itself; each pipeline module is added by the milestone that implements it.
   No linter or formatter yet.
2. **M1 — Video download**: `src/extract_memes/downloader.py` uses `yt-dlp` to download a
   YouTube URL into `downloads/`.
3. **M2 — Frame extraction**: `src/extract_memes/frame_extractor.py` uses `opencv-python`
   (`cv2.VideoCapture`, bundled FFmpeg backend — no separate system `ffmpeg` install needed) to
   sample frames at a default of 1 fps.
4. **M3 — Classifier interface (stub only)**: `src/extract_memes/classifier.py` defines the
   `FrameClassifier` interface, with a stub implementation (e.g. always-true, or an interactive
   y/n prompt) — no ML yet.
5. **M4 — Save output + CLI wiring**: `src/extract_memes/pipeline.py` orchestrates M1→M2→M3
   and writes flagged frames to `output/`; `extract-memes <youtube_url>` runs it all. First
   fully runnable milestone.
6. **M5 — Checkpoint**: with real output in hand, confirm or adjust the sampling rate, and
   decide whether dedup is needed now or can wait until M7.
7. **M6 — Real classifier**: pick the classification approach using real sample
   frames as evaluation data; replace the M3 stub behind the same interface. Gets its own ADR and spec.
8. **M7 — Dedup** (if deferred from M5): near-duplicate frame suppression, e.g. perceptual
   hashing via `imagehash`.

Dev process: solo project on `main`, no CI for now. Each milestone adds its module and matching
tests under `tests/` together, and is also validated by running it against one real short
YouTube video. How to handle tests that need network access is decided in the M1 spec. Each
milestone follows the normal spec-driven workflow: it gets its own spec in `specs/features/`,
which must reach `ready` before implementation starts.

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
- Writing a spec for every milestone, including small ones like M0, adds some overhead before
  each step. We accept that cost to keep the spec-driven workflow consistent.

---

## References

- `CLAUDE.md` — Project Overview (pipeline description)
- `specs/features/project-setup.md` — M0 spec