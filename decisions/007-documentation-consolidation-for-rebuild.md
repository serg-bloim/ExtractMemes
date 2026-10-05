# 007 — Consolidate Specs and ADRs as the Source of Truth for a From-Scratch Rebuild

**Date:** 2026-09-16
**Status:** Accepted

---

## Context

ExtractMemes reached a working state in one day of fast iteration. The workflow in ADR 001 was
followed at first. Later, many changes landed in commits titled only "upd", with no spec or ADR
update, or with specs only half-updated. By the end:

- Several specs contradicted the code. The extraction-pipeline spec still promised `.png` output,
  file names without frame indices, and a required `source` argument. The video-download spec
  described pre-muxed format selection that no longer works on YouTube. The project-setup spec
  still listed `output/`.
- Some important decisions and knowledge existed **only in code**. The user-authored classifier
  prompt, the `wv*`/`bv*` format selectors, the Node.js JS runtime, `static-ffmpeg`, and the dev
  scripts had no written record.
- Some defects were never noticed: `*` in download file names, `watch?v=` URLs all mapping to the
  run name `watch`, import-time side effects, and tests that silently scan a one-hour video or
  write into the project directory.

The user decided to **erase the code and recreate it from the documents**. The documents therefore
have to be complete, correct, and unambiguous enough to rebuild the working tool, without
re-introducing the known defects.

## Decision

1. **Specs are the normative source for the rebuild.** Each feature spec was rewritten so its
   acceptance criteria describe the working behavior plus fixes for the defects found in review.
   Every behavior-bearing detail that previously lived only in code is now in a spec: exact
   commands, file-name formats, defaults, error contracts, and the verbatim classifier prompt.
2. **Undocumented decisions were recorded retroactively:**
   [ADR 006](006-youtube-video-only-formats-and-download-toolchain.md) (YouTube formats and download
   toolchain) and the new [dev-harness spec](../specs/features/dev-harness.md) (`run_real_video.py`,
   `playground/`).
3. **All feature specs are reset to `ready` with unchecked acceptance criteria.** The rebuild checks
   them off again, and each spec moves to `implemented` only when all of its criteria hold, per
   ADR 001. Every spec's Changelog keeps the history.
4. **Rebuild order**, following the `depends-on` frontmatter:
   1. [project-setup](../specs/features/project-setup.md): skeleton, `pyproject.toml`,
      `.gitignore`, `slow` marker.
   2. [video-download](../specs/features/video-download.md)
   3. [frame-extraction](../specs/features/frame-extraction.md)
   4. [meme-classifier](../specs/features/meme-classifier.md)
   5. [extraction-pipeline](../specs/features/extraction-pipeline.md): pipeline and CLI.
   6. [dev-harness](../specs/features/dev-harness.md)
5. **What gets erased and what stays.**
   - **Erased and rebuilt:** `src/`, `tests/`, `playground/`, `run_real_video.py`, `pyproject.toml`.
   - **Kept:** `CLAUDE.md`, `JOURNAL.md`, `specs/`, `decisions/`, `.gitignore` (already matches
     project-setup AC5).
   - **Not code, and must not be deleted as part of the rebuild:** `sample/` (fixtures),
     `.runtime/experiment/` (the labeled classifier evaluation set; see the register, item 40).
6. **Rebuild is done when:**
   - `pytest -m "not slow"` passes offline without `claude` installed;
   - `pytest -m slow` passes with network and Node.js;
   - `extract-memes sample/short.mp4` flags the two known meme cards (≈10.56 s and ≈28.80 s) and
     none of the portrait-video look-alikes. This is a smoke check, since the classifier isn't
     deterministic.

## Options Considered

### Option A: Keep the code, patch the docs to match it

**Rejected by the user:** the code grew messily, and a clean rebuild from corrected specs is the
goal.

### Option B: Rebuild from the existing docs as they were

**Rejected:** the rebuild would re-create the contradictions and lose the prompt, format
selectors, and toolchain decisions that existed only in code.

### Option C: Consolidate the docs first, then rebuild from them (chosen)

This is the only option that carries the knowledge over. It also exercises ADR 001's premise that
specs alone are enough to regenerate the implementation.

## Consequences

**Positive:**
- A rebuild can proceed spec by spec without reading the old code.
- Every issue found during development has a recorded resolution (register below), so a rebuild
  won't rediscover them the hard way.

**Negative / costs:**
- Specs are longer and more prescriptive than the template suggests. They now pin exact file
  names, CLI arguments, and prompt text. Here that's deliberate: those details are observable
  behavior the user relies on.
- Status `ready` sits next to code that still exists until the erase happens. Treat the specs, not
  that code, as authoritative.

## Issue Register

Every issue or question found during development or in this consolidation review, with its
resolution.

**State values:**
- **Resolved:** fixed during development; the fix is carried into the specs.
- **Rebuild fix:** a defect in the current code, fixed by a spec criterion for the rebuild.
- **Documented:** a known behavior or limitation we accept.
- **Open:** a deliberately unresolved question that doesn't block the rebuild.

### A. Process and workflow

| # | Issue / question | Resolution | State | Where |
|---|---|---|---|---|
| 1 | The first spec covered the whole project goal, which was too broad to implement or validate. | Deleted it. Milestone plan plus one spec per module. | Resolved | ADR 002 |
| 2 | Should the classifier decision be made before any real frames exist? | Initially deferred behind a stub (walking skeleton), then superseded when the user asked for the real Claude classifier from the start. | Resolved | ADR 002, ADR 004 |
| 3 | JOURNAL.md grew into a verbose narrative that duplicated spec detail. | One-line index; detail goes in the spec Changelog or ADR. | Resolved | ADR 003 |
| 4 | Many changes landed in "upd" commits without spec updates, so docs drifted from code. | This consolidation: retroactive ADR 006, dev-harness spec, and spec rewrites. | Resolved | ADR 007 |

### B. Downloading

| # | Issue / question | Resolution | State | Where |
|---|---|---|---|---|
| 5 | Scanning a full-resolution copy wastes bandwidth and time. | Two tiers: scan a worst-quality copy, extract from a best-quality copy. | Resolved | ADR 004 |
| 6 | We need to develop and test offline, without YouTube. | A local file path passes straight through `download()`. | Resolved | video-download AC2 |
| 7 | YouTube no longer serves pre-muxed `worst`/`best` formats ("Requested format is not available"). | Video-only-capable selectors `wv*[ext=mp4]/wv*` and `bv*[ext=mp4]/bv*`. | Resolved | ADR 006, video-download AC3 |
| 8 | yt-dlp warns that YouTube extraction without a JS runtime is deprecated; `deno` isn't installed. | `js_runtimes={"node": {}}`. Node.js becomes a prerequisite for URLs. | Resolved | ADR 006, video-download AC5 |
| 9 | Without ffmpeg, HLS downloads are MPEG-TS bytes in a `.mp4` file, and yt-dlp warns. | `static-ffmpeg` provides ffmpeg, and yt-dlp remuxes to real MP4. | Resolved | ADR 006, video-download AC6 |
| 10 | The workaround passed raw selectors as `quality`, producing `downloads/<id>_bv*.mp4` (`*` in the file name) and breaking the `Literal` type. | Keep `worst`/`best` in the API and file names, and map to selectors internally. | Rebuild fix | video-download AC1, AC4 |
| 11 | `static_ffmpeg.add_paths()` ran at import time, even for `--help`, local runs, and unit tests (possible network fetch, `PATH` change). | Call it lazily, only before a URL download. The package has no import-time side effects. | Rebuild fix | video-download AC6, project-setup AC2 |
| 12 | The mocked download unit test still asserted the obsolete `worst[ext=mp4]/worst` selector. | Tests assert the mapping for both tiers. | Rebuild fix | video-download AC9 |
| 13 | Real downloads weren't tested at all. | `slow`-marked tests against the permanent test video, now also checking the MP4 `ftyp` header and resolution order. | Resolved (strengthened) | video-download AC10 |
| 14 | A mistyped local path is silently treated as a URL. | The yt-dlp error is wrapped with the source in the message. Accepted. | Documented | video-download Technical Notes |
| 15 | Re-downloading the same URL. | yt-dlp skips existing files by default (deterministic names). Incidental caching, not a guarantee. | Documented | video-download Out of Scope |

### C. Frame extraction

| # | Issue / question | Resolution | State | Where |
|---|---|---|---|---|
| 16 | Avoid a system ffmpeg for decoding. | `opencv-python-headless` with its bundled FFmpeg (headless because nothing is ever displayed). | Resolved | frame-extraction Technical Notes |
| 17 | Two different reads are needed: a dense scan and an exact-timestamp read. | `sample_frames` decodes sequentially; `frame_at` seeks by `POS_MSEC`. | Resolved | frame-extraction AC1–AC4 |
| 18 | Is `POS_MSEC` seeking accurate enough, especially on the VP9 best file? | Verified pixel-identical to sequential decode on H.264 and VP9. | Resolved | frame-extraction AC9, Technical Notes |
| 19 | The "2 fps" default really samples at 2.083 fps (`round(12.5) == 12`, so steps are 0.48 s). | Keep and document it. Existing artifacts and known timestamps depend on it. | Documented | frame-extraction AC2, Q3 |
| 20 | `CAP_PROP_FRAME_COUNT` is wrong for some files (`short2.mp4`: 1611 reported, 1501 decoded). | Never use it for correctness, which is why the progress bar has no total. | Documented | frame-extraction AC3; pipeline Out of Scope |
| 21 | Frame numbers weren't available for file names. | `sample_frames` yields the real decoded frame index. | Resolved | frame-extraction AC1 |
| 22 | `numpy` is imported directly but was only a transitive dependency. | Declare it explicitly. | Rebuild fix | project-setup Technical Notes |

### D. Classification

| # | Issue / question | Resolution | State | Where |
|---|---|---|---|---|
| 23 | No `ANTHROPIC_API_KEY` or `anthropic` SDK is available. | Shell out to the already-authenticated `claude -p` CLI. | Resolved | ADR 004, meme-classifier Q1 |
| 24 | A batch run can't answer permission prompts. | `--allowedTools=Read`, with `cwd` set to the image's folder and a bare file name in the prompt. | Resolved | meme-classifier AC3 |
| 25 | `--allowedTools` is variadic, so the space form could swallow the prompt. | Always pass the single token `--allowedTools=Read`. | Documented | meme-classifier Technical Notes |
| 26 | What if the answer is ambiguous, the call fails, or it times out? | Raise `RuntimeError`, never a silent default. Timeout 60 s. | Resolved | meme-classifier AC5, AC6 |
| 27 | The v1 generic prompt flagged presenter frames with an inset thumbnail. | v2 prompt describing the reveal pattern (centered image, dark background, static). | Resolved | ADR 005, meme-classifier prompt history |
| 28 | The v2 prompt flagged portrait videos with blurred or black pillarbox bars (15 of 17 detections false). | v3 user-authored "glitch-framed meme card" rubric; validated with exactly 2 of 2 true positives on `short.mp4`. | Resolved | meme-classifier AC4, prompt history |
| 29 | The prompt existed only in code and would be lost in the erase. | Embedded verbatim in the spec (verified byte-identical). | Resolved | meme-classifier "Prompt (verbatim)" |
| 30 | Model and effort weren't configurable. | Constructor params, `pipeline.run` params, and CLI flags; defaults haiku-4.5 / `low`. | Resolved | meme-classifier AC2, Q4; pipeline AC9 |
| 31 | A missing `claude` binary leaked a raw `FileNotFoundError`. | Wrap it in an actionable `RuntimeError`. | Rebuild fix | meme-classifier AC6 |
| 32 | Throughput is ~8–11 s per frame, sequential: ~43 min for a 78 s video, ~17 h+ for a 1-hour video. | Not solved. Candidates: batching, parallel calls, API SDK, a cheap local pre-filter, or a lower fps. | Open | meme-classifier Technical Notes |
| 33 | Each call starts a full Claude Code session inside the project tree: it may load `CLAUDE.md`, settings, and hooks, and it saves a transcript per frame. | Not measured. Candidate flags: `--no-session-persistence`, `--setting-sources`, `--bare`. | Open | meme-classifier Technical Notes |
| 34 | A chatty answer like "can't say yes or no" parses as YES (the first word wins). | Accepted, since the prompt demands one word. Not seen in practice. | Documented | meme-classifier Technical Notes |

### E. Pipeline, CLI, and output

| # | Issue / question | Resolution | State | Where |
|---|---|---|---|---|
| 35 | Artifacts went to `/tmp`, and scan frames were deleted. | Keep everything under `.runtime/<run>/{frames,saved}/`, and never delete frames. | Resolved | ADR 005, pipeline AC2, AC4 |
| 36 | Long scans gave no feedback. | `tqdm` bars "Scanning frames" and "Extracting memes". | Resolved | pipeline AC6 |
| 37 | Discovered memes weren't visible until the whole scan finished. | Write `saved/thumb_frame_*.jpg` immediately when a frame is flagged. | Resolved | pipeline AC2 step 3 |
| 38 | It was hard to relate files to video positions. | File names `…_<idx:06d>_<ts:.2f>s.jpg`. PNG changed to JPEG everywhere. | Resolved | pipeline AC3, Q2 |
| 39 | `watch?v=<id>` URLs all got the run name `watch`, so runs of different videos collided. | Use the `v` query parameter. | Rebuild fix | pipeline AC5 |
| 40 | The labeled evaluation set (15 positive / 23 negative) lives in gitignored, "disposable" `.runtime/experiment/`. | Recommend moving it to `sample/experiment/` (a user action). Never delete it during the rebuild. | Open | meme-classifier Technical Notes |
| 41 | The spec said `source` is a required positional; the code prints help when it's missing. | Optional positional; no argument prints help and exits 0. | Resolved (spec corrected) | pipeline AC10, Q4 |
| 42 | Default paths resolve against the cwd, not the project root. | Accepted; run from the project root. | Documented | pipeline Technical Notes |
| 43 | Where should downloads live: CLI `downloads/` or the dev runner's `.runtime/downloads/`? | Keep both as they are. Changing the CLI default would be a separate decision. | Documented | pipeline Q6, dev-harness AC3 |
| 44 | The same meme can be flagged in consecutive samples (duplicates). | Flagged frames within `--merge-window` (1 s) of a meme's first flagged frame are merged into one meme ([meme-merge-window](../specs/features/meme-merge-window.md)). Perceptual dedup (ADR 002 M7) still deferred. | Resolved | pipeline Out of Scope |
| 45 | `--classifier-effort` can't express "omit effort" from the CLI. | Accepted; `None` is available from Python only. | Documented | pipeline Out of Scope |
| 46 | Could a scan-file frame index mismatch the best file if the tiers' fps differ? | Seek by time (correct). The index in file names always refers to the scan file. | Documented | frame-extraction Technical Notes |

### F. Tests and dev tooling

| # | Issue / question | Resolution | State | Where |
|---|---|---|---|---|
| 47 | Spawning real `claude` from pytest is slow, costly, and recursive. | The classifier is always mocked in tests, and a fake `FrameClassifier` is injected in pipeline tests. | Resolved | meme-classifier AC7, pipeline AC12 |
| 48 | A frames glob looked for `.png` while the pipeline wrote `.jpg`. | Fixed. Tests match the JPEG naming regex. | Resolved | pipeline AC12 |
| 49 | The no-memes test scanned `sample/full.mp4` (~1 h, 7842 JPEG writes) with no skip guard for that file. | Use `short.mp4`, and also assert the best-quality download is skipped. | Rebuild fix | pipeline AC13 |
| 50 | `tests/test_with_real_video.py` hit the network without a `slow` marker, wrote into the project's `downloads/`/`.runtime/`, and returned a value. | `slow`-marked, `tmp_path`, asserts instead of returning. | Rebuild fix | pipeline AC16 |
| 51 | `run_real_video.py` imported `src.extract_memes` (bypassing the install, leaving a root `__pycache__/`). | Import the `extract_memes` package. | Rebuild fix | dev-harness AC4 |
| 52 | `playground/pb.py` only worked with cwd `playground/`; the playground `__main__` ran a throwaway loop. | The playground `__main__` runs the progress demo; `pb.py` is removed. | Rebuild fix | dev-harness AC7 |
| 53 | Fixtures aren't in git, and the network tests need a stable video. | Fixture inventory documented; `/sample/` stays gitignored; permanent test video `AElGyY97k_0`. | Documented | project-setup Technical Notes |

### G. Documentation defects fixed in this pass

| # | Issue | Resolution | State | Where |
|---|---|---|---|---|
| 54 | `decisions/README.md` heading read `4# Architecture Decision Records`. | Fixed. | Resolved | decisions/README.md |
| 55 | CLAUDE.md's Project Overview still said the classification approach was "TBD". | Updated to describe the two-tier Claude CLI design. | Resolved | CLAUDE.md |
| 56 | The ADR 002 and 004 status lines didn't mention the format and toolchain change. | Status lines point to ADR 006. | Resolved | ADR 002, ADR 004 |

## References

- [ADR 001](001-spec-driven-workflow.md): the workflow this consolidation restores.
- [ADR 004](004-claude-classifier-and-dual-resolution-download.md), [ADR 005](005-runtime-layout-and-classifier-checkpoint.md), [ADR 006](006-youtube-video-only-formats-and-download-toolchain.md)
- `specs/features/*.md`: all six feature specs.
