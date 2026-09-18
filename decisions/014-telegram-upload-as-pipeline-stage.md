# 014 — Upload Extracted Memes to Telegram as a Pipeline Stage

**Date:** 2026-09-18
**Status:** Accepted

---

## Context

Extracted memes only ever land as local files under `.runtime/<run-name>/clean/` (or
`high-res/meme_<n>/` with `--clean-method none`). The user wants a single `extract-memes` run to
also deliver those images to a Telegram chat, without a second manual step and without turning
this into a separate distributable package.

Two shapes were on the table: a separate command run afterward against an already-extracted run's
output directory, or a stage wired into `pipeline.run` itself, gated by a new CLI flag. This also
introduces the project's first external messenger dependency, so how to talk to Telegram (a full
SDK vs. a direct HTTP call) and how upload failures should behave both needed deciding before
writing the spec.

## Decision

1. **Upload is a pipeline stage, not a separate command.** `pipeline.run` gains an optional
   `uploader: Uploader | None` parameter (plus `upload_to`, `telegram_bot_token`,
   `telegram_chat_id` for CLI wiring, mirroring how `classifier`/`classifier_type` already work).
   When set, every image the run saves is uploaded before `run` returns. This piggybacks on
   `pipeline.run`'s own already-known output list, so there's no separate step that has to
   rediscover which directory (`clean/` vs `high-res/`) holds "the" output for a given run — a
   real ambiguity a standalone command would have had to resolve on its own.
2. **New `Uploader` ABC** in `src/extract_memes/uploader.py`, with one abstract `upload(image_path:
   Path) -> None`, in the same shape as `FrameClassifier` in `classifier.py`. `TelegramUploader` in
   its own module (`telegram_uploader.py`) is the first (only) implementation, following the same
   one-interface-file, one-file-per-implementation convention `HeuristicClassifier` established
   (ADR 008).
3. **Talk to the Telegram Bot API directly over HTTP** (`POST
   https://api.telegram.org/bot<token>/sendPhoto`, multipart), using `requests`, instead of adding
   `python-telegram-bot`. Sending a photo is one HTTP call; a bot-framework library would pull in
   an async event loop and update-polling machinery this project never uses.
4. **An upload failure logs and continues**, instead of aborting the run. This is a deliberate
   departure from the existing rule that any exception from `download`/`sample_frames`/
   `frames_from`/the classifier propagates and aborts the run (extraction-pipeline spec AC8): those
   are failures of steps that produce the run's own artifacts, where a partial result is not
   trustworthy; a failed upload is a delivery problem for an artifact that's already safely on
   disk, and one flaky send (or one oversized/rejected image) shouldn't cost every other meme the
   run already found.
5. **Credentials are validated before anything downloads.** The CLI checks that
   `--telegram-bot-token`/`--telegram-chat-id` (or their `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`
   env-var fallbacks) resolve to something as soon as `--upload-to telegram` is given, and exits
   via `parser.error` (matching how `--no-images --save-high-res` is already rejected) rather than
   running the whole pipeline first and failing at the very end.

## Options Considered

### Option A: Separate `extract-memes-upload <run-name>` command (rejected)

Decouples upload from extraction; a run could be uploaded later, or re-uploaded. Rejected because
the user explicitly wants one command to do the whole job, and because it reintroduces the
`clean/`-vs-`high-res/` ambiguity that the pipeline itself doesn't have to resolve, since it
already knows exactly what it just wrote.

### Option B: `python-telegram-bot` library (rejected)

Gives structured API bindings and retry helpers. Rejected: it's built around a bot event loop and
polling updates, none of which this project needs for one-way `sendPhoto` calls. A direct HTTP
call is a few lines against a stable, documented endpoint.

### Option C: Abort the run on any upload failure (rejected)

Consistent with the pipeline's existing all-or-nothing error propagation. Rejected by the user:
losing every other successfully-found meme because one upload failed is a worse outcome than a
partial delivery with a clear log line about what didn't go through.

## Consequences

**Positive:**
- One command produces and delivers memes; no second manual step, no separate package.
- The `Uploader` ABC is ready for a second implementation (Discord, Slack) the same way
  `HeuristicClassifier` was added alongside `ClaudeCliClassifier`, without touching
  `pipeline.run`'s wiring pattern.
- No new ambiguity about which output directory is authoritative, since upload always sends
  exactly what `pipeline.run` already decided to save (AC2 in the accompanying spec).

**Negative / costs:**
- **New runtime dependency**: `requests`.
- **`pipeline.run`'s signature grows again** (four new parameters), continuing a trend this spec
  doesn't address on its own — the function has accreted a parameter per iteration since ADR 005.
- **Inconsistent error philosophy**: this is the first "log and continue" step in a pipeline whose
  every other stage aborts on error. A reader has to know upload is the exception, not the rule
  (documented in the spec's Technical Notes).
- **No re-upload / dedup across runs.** Re-running the same `run_name` will re-upload every image
  again, since there is no upload-state manifest. Left explicitly out of scope; flagged as an open
  question if it's needed later.

## References

- [meme-upload spec](../specs/features/meme-upload.md): the accompanying spec, acceptance criteria
  for the exact wiring.
- [ADR 008](008-heuristic-classifier-iteration.md): the interface-plus-per-implementation-file
  convention this follows for `Uploader`/`TelegramUploader`.
- [extraction-pipeline spec](../specs/features/extraction-pipeline.md) AC8: the error-propagation
  rule this decision deliberately departs from for uploads only.
