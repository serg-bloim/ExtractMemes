# 004 — Classify with Claude Code Now; Scan Low-Res, Extract High-Res

**Date:** 2026-09-16
**Status:** Accepted; partially superseded by [006](006-youtube-video-only-formats-and-download-toolchain.md).
YouTube no longer offers pre-muxed `worst`/`best` formats, so downloads now use video-only
`wv*`/`bv*` selectors with a Node.js JS runtime and bundled ffmpeg. The two-tier scan/extract
design and the Claude CLI classifier are unchanged. Output layout was later changed by
[005](005-runtime-layout-and-classifier-checkpoint.md).

---

## Context

ADR 002 planned a walking skeleton: build download → extract → save first with a stubbed
classifier (`FrameClassifier.is_meme(frame) -> bool` always returning `True` or prompting a
human), and defer the real classifier decision to M6, made against real extracted frames.

The user has now asked to implement the whole pipeline in one pass, using **Claude** to do the
real classification from the start, and described a specific download strategy: download the
video in the **worst available resolution** first to find which timecodes contain memes, then
download it again in a **fine resolution** to extract the actual meme frames at those timecodes.

This changes two things ADR 002 assumed:

1. The classifier is no longer stubbed — it's real, and decided now instead of at M6.
2. The pipeline downloads the source video **twice**, at two different qualities, instead of
   once. Frame extraction happens twice too: a cheap low-res sampling pass for classification,
   and a precise high-res pass at only the flagged timecodes.

A concrete test asset, `sample/short.mp4` (78s, 144p, several memes), was provided to validate
the pipeline end-to-end without needing a live YouTube download during development.

We also confirmed in-session: this machine has no `ANTHROPIC_API_KEY` and no `anthropic` SDK
installed, but does have the `claude` CLI (Claude Code itself) on `PATH`, already authenticated.
It supports non-interactive use via `claude -p` (print mode, exits after one response), and
`--allowedTools` to pre-approve specific tools (e.g. `Read`) without prompting — which matters
because a batch classification run cannot sit at an interactive permission prompt.

## Decision

**Classifier:** Implement `ClaudeCliClassifier` now (not a stub) as the one and only
`FrameClassifier` implementation. It shells out to `claude -p --allowedTools Read` with a prompt
that tells Claude to read a given frame image file and answer only `YES` or `NO` to whether it's
a meme. This reuses the developer's existing authenticated Claude Code session — no separate API
key or `anthropic` SDK dependency needed. This supersedes ADR 002's M3 (stub) and M6 (deferred
real classifier, evaluated by ADR/spec of its own) — there is now one classifier milestone, done
with real classification from the start.

**Download/extraction, two resolutions:**
1. Download the source once at **worst** quality into `downloads/`.
2. Sample frames from the worst-quality file at a fixed rate (default 1 fps, per ADR 002 M2) and
   classify each with `ClaudeCliClassifier`. Record the timestamp (seconds) of every frame
   classified as a meme.
3. Download the source again at **best** quality into `downloads/`.
4. For each flagged timestamp, seek the best-quality file to that exact timestamp and save that
   single frame to `output/` as the final meme image.

If the given source is already a local file path (not a URL — used for `sample/short.mp4` and
any future local testing), the download step is skipped entirely and that file is used directly
for both the scan and extraction passes. This is a convenience for local/offline testing, not a
new pipeline concept — the two-resolution logic still exists, it's just a no-op when there's only
one local file to use.

**Milestone renumbering:** This collapses ADR 002's M1–M4 (and M6) into four modules, each still
getting its own spec:
- `downloader.py` — download at a given quality, or pass through a local file.
- `frame_extractor.py` — sample frames at a fixed fps, or extract one frame at an exact timestamp.
- `classifier.py` — `FrameClassifier` interface + `ClaudeCliClassifier`.
- `pipeline.py` + CLI wiring — orchestrates scan pass → extraction pass → save.

M5 (checkpoint) and M7 (dedup) from ADR 002 are unaffected and still deferred.

## Options Considered

### Option A: Keep the stub classifier, implement two-pass download separately (ADR 002 as-is)

Build the mechanical two-pass pipeline now, keep classification stubbed until M6.

**Rejected:** The user explicitly asked for Claude-based classification now, and a stub would
make the "worst resolution" scan pass pointless (it exists specifically to cheaply find meme
timecodes via classification).

### Option B: Classify via the Anthropic API (`anthropic` SDK) with vision-capable model

Add `anthropic` as a runtime dependency, call the Messages API with base64-encoded frame images
and `ANTHROPIC_API_KEY`.

**Rejected for now:** No API key is configured in this environment, and the user has been using
Claude Code interactively (this very CLI) to eyeball sample frames earlier in this session. The
`claude` CLI is already installed and authenticated, so shelling out to it needs no new
credential and matches how the user is already using Claude. Revisit as an ADR of its own if
per-call latency/cost of spawning a CLI process per frame becomes a real problem — the
`FrameClassifier` interface makes that swap a contained change.

### Option C: Single download, classify and extract from the same (best-quality) copy

Download once at best quality, sample+classify+extract all from that one file.

**Rejected:** Ignores the user's explicit instruction and its rationale — scanning many sampled
frames at full resolution wastes bandwidth/time when only the resolution needed for a yes/no
meme judgment is required for scanning; full quality is only needed for the frames actually kept.

## Consequences

**Positive:**
- One real, working classifier from day one — no separate M6 milestone or ADR needed later.
- The two-resolution split keeps the expensive part (full-res download) proportional to what's
  actually flagged as memes, not the whole video.
- `FrameClassifier` stays an interface with one implementation; swapping in an API-based or local
  ML classifier later is a contained change, not a pipeline rewrite.

**Negative / costs:**
- Classification latency is bounded by spawning one `claude` process per sampled frame
  (sequential, a few seconds each). Fine for a short demo video; would need batching or
  parallelism for long videos — noted as a future concern, not solved here.
- The pipeline depends on the `claude` CLI being installed and authenticated on the machine
  running it, which is an unusual runtime dependency for a Python package (documented in the
  classifier spec's Technical Notes, not hidden).
- Two full downloads of the source video instead of one, plus two decode passes over the
  low-res file's frames (sampling) and the high-res file (seeking) — acceptable for the stated
  goal but adds wall-clock time vs. a single-pass design.

## References

- `decisions/002-meme-extraction-pipeline-rollout-plan.md` — superseded in part (M1, M3, M4, M6
  folded into this ADR's design)
- `specs/features/video-download.md`
- `specs/features/frame-extraction.md`
- `specs/features/meme-classifier.md`
- `specs/features/extraction-pipeline.md`
- `sample/short.mp4` — validation asset used during implementation
