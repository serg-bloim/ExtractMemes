---
title: "Upload Extracted Memes to Telegram"
status: implemented
created: 2026-09-18
updated: 2026-09-18
author: ""
depends-on: ["extraction-pipeline", "batch-cleaning"]
---

# Upload Extracted Memes to Telegram

## Problem Statement

Extracted memes only ever land as local files under `.runtime/<run-name>/`. A user who wants them
delivered to a chat where people actually see them has to move them there by hand after every run.
There is currently no way for a single `extract-memes` invocation to also send its output
somewhere.

## Amends

This is an iteration spec, layered on [extraction-pipeline](extraction-pipeline.md). It applies
only when upload is requested (`upload_to="telegram"` / `--upload-to telegram`); a run without it
is unchanged in every respect.

| Earlier spec | Criterion | Amended by |
|---|---|---|
| [extraction-pipeline](extraction-pipeline.md) | AC1: `pipeline.run`'s parameter list | AC1 |
| [extraction-pipeline](extraction-pipeline.md) | AC2 step 7: `run` returns the collected paths | AC5 (upload happens before returning, doesn't change what's returned) |
| [extraction-pipeline](extraction-pipeline.md) | AC9: the CLI's flag list | AC8 |

## User Story

**Primary:**
As a user running `extract-memes` against a video, I want the extracted memes automatically sent
to a Telegram chat, so that one command both produces and delivers the memes without a manual
upload step.

## Acceptance Criteria

### Library: `pipeline.run` / `Uploader`

- [x] AC1: `src/extract_memes/uploader.py` defines
      `class Uploader(ABC)` with one abstract method
      `upload_all(self, image_paths: list[Path], source: str) -> None` (raises only if delivery
      couldn't be attempted at all; implementations should log and keep going past a single
      item's failure where possible).
- [x] AC2: `src/extract_memes/telegram_uploader.py` defines `TelegramUploader(Uploader)`.
      `__init__(self, bot_token: str | None = None, chat_id: str | None = None)` resolves
      `bot_token`/`chat_id` from the arguments first, then the `TELEGRAM_BOT_TOKEN`/
      `TELEGRAM_CHAT_ID` environment variables, and raises `ValueError` immediately if either is
      still unresolved. `upload_all` (AC5) talks to the Bot API over `requests`, treating a
      response whose JSON body has `"ok": false` as a failure (not just a non-2xx HTTP status —
      confirmed necessary during live testing against a real bot and chat).
- [x] AC3: `pipeline.run` gains four trailing keyword parameters:
      `uploader: Uploader | None = None`, `upload_to: Literal["telegram"] | None = None`,
      `telegram_bot_token: str | None = None`, `telegram_chat_id: str | None = None`. All other
      parameters and their defaults are unchanged. Tests inject a fake `uploader` directly,
      without needing real Telegram credentials.
- [x] AC4: If `uploader` is `None` and `upload_to == "telegram"`, `run` constructs
      `TelegramUploader(bot_token=telegram_bot_token, chat_id=telegram_chat_id)` before creating
      any run directory or starting any download. A `ValueError` from that construction (AC2)
      propagates immediately, same as the existing `clean_method` validation.
- [x] AC5: If `uploader` is not `None` after AC4, `run` calls
      `uploader.upload_all(saved, source)` exactly once, right before returning `saved` — after
      the extraction loop, regardless of whether `save_timecodes` also runs. `source` is `run`'s
      own `source` argument (the video's URL or local path), unchanged. What's passed is always
      exactly `saved` — whether that's `clean/meme_<n>.png` files or, with `clean_method=None` and
      `save_high_res=True`, the individual batch frames — no separate logic decides what counts as
      "the" output for uploading.
- [x] AC6: `TelegramUploader.upload_all` (AC2) does the actual delivery: it posts `source` as one
      Telegram message, then posts every image in `image_paths` as a reply to that message, in
      albums (`sendMediaGroup`) of up to 10 images each (Telegram's limit) — so 3 images make one
      album, 12 images make two (10 then 2). If posting the source message itself fails, the
      albums are still sent, just without `reply_to_message_id` (delivering the images matters
      more than the link they'd have replied to). A failed album is caught, printed as
      `Upload failed for <names>: <error>`, and the remaining albums still send; a failed source
      message is printed as `Failed to post the source link: <error>`. If any album failed,
      `upload_all` prints a final `<N> of <M> uploads failed.` line, `N` counted in images. None of
      this raises out of `upload_all` in the ordinary case.
- [x] AC6b: An exception that does escape `uploader.upload_all()` (e.g. a totally unreachable
      network) does **not** abort the run: `pipeline.run` catches it, prints `Upload failed:
      <error>`, and returns `saved` unaffected — `saved` always reflects what was saved locally,
      never what was successfully delivered.
- [x] AC7: `no_images=True` combined with `uploader is not None` or `upload_to is not None` raises
      `ValueError` before creating anything, the same way `no_images=True, save_high_res=True`
      already does — there is nothing to upload when no images are produced.

### CLI

- [x] AC8: `src/extract_memes/__main__.py` adds:
      - `--upload-to` (choices `telegram`, default `None`): upload each saved meme image as the
        run finishes.
      - `--telegram-bot-token` (default `None`): falls back to `TELEGRAM_BOT_TOKEN`.
      - `--telegram-chat-id` (default `None`): falls back to `TELEGRAM_CHAT_ID`.

      All three are passed straight through to `pipeline.run` as `upload_to`, `telegram_bot_token`,
      `telegram_chat_id`.
- [x] AC9: With `--upload-to telegram` given, `main()` resolves the bot token and chat id the same
      way `TelegramUploader` does (flag, then env var) and calls `parser.error(...)` — exit code
      2, before `pipeline.run` is called at all — if either is still missing. This mirrors the
      existing `--no-images --save-high-res` pre-check (AC10 of no-images.md) rather than relying
      on catching the pipeline's `ValueError`.
- [x] AC10: `--upload-to telegram --no-images` is rejected by this same pre-check with
      `parser.error`, for the same reason as AC7.

### Tests

- [x] AC11: `tests/test_uploader.py`: a fake concrete `Uploader` records each `upload_all` call
      (paths and source); the ABC cannot be instantiated directly.
- [x] AC12: `tests/test_telegram_uploader.py`: `requests.post` is mocked (never hits the network).
      Covers: the source is posted via `sendMessage` before any album; images are chunked into
      `sendMediaGroup` calls of at most 10, each replying to the source message; an empty
      `image_paths` makes no requests at all; a failed source message still lets the albums send,
      without a reply; a failed album is logged and the rest still send, with a correct
      `<N> of <M>` count; every opened image file is closed after its album; missing bot
      token/chat id (no args, no env vars) raises `ValueError` before any request; env var fallback
      works when the argument is omitted.
- [x] AC13: `tests/test_pipeline.py`: a fake `Uploader` passed as `uploader=` receives exactly one
      `upload_all(saved, source)` call, for both a `clean_method` run and a `clean_method=None,
      save_high_res=True` run. A run with no `uploader` never constructs or calls one. A fake
      `Uploader` whose `upload_all` raises still lets the run finish, still returns the full
      `saved` list, and the `Upload failed: <error>` line is captured with `capsys`.
      `no_images=True` with `upload_to="telegram"` raises `ValueError` before any directory is
      created.
- [x] AC14: `tests/test_cli.py`: `--upload-to telegram` with no credentials anywhere exits 2 via
      `parser.error`; with `--telegram-bot-token`/`--telegram-chat-id` (or the env vars set) it
      reaches `pipeline.run` with `upload_to="telegram"` and the resolved values passed through;
      `--upload-to telegram --no-images` exits 2.

## Out of Scope

- **Discord, Slack, or any messenger besides Telegram.** The `Uploader` ABC is designed for this,
  but adding a concrete implementation is a separate spec, the same way `HeuristicClassifier` got
  its own spec alongside `meme-classifier`.
- **A standalone upload command** decoupled from a pipeline run (considered and rejected —
  [ADR 014](../../decisions/014-telegram-upload-as-pipeline-stage.md)).
- **Retry/backoff on a failed album.** One attempt per album; a failure is logged, not retried.
- **Dedup or skip-if-already-uploaded across separate runs of the same video.** Re-running the same
  `run_name` re-posts everything again (a new source message, new albums); there is no
  upload-state manifest. Would need its own spec if needed later, since it touches the runtime
  directory's output contract.
- **Real Telegram forum-topic threads** (`createForumTopic`). Tried during live testing and
  rejected: it only works when the target chat is a supergroup with Topics enabled, which isn't
  true of the chat this was tested against, and there's no way to detect or configure that from
  the pipeline. The reply-to-the-source-message approach (AC6) works in any chat type.
- **Publishing to Telegraph (telegra.ph) and posting a page link instead of raw photos.** Tried and
  abandoned: `telegra.ph/upload` (the only image-upload path Telegraph has — it isn't in their
  documented API) returned `"Unknown error"` for every attempt during live testing, including a
  trivial 1x1 test image sent with `curl` outside this codebase, indicating the endpoint itself is
  unreliable rather than anything about our images or request shape.
- **Posting to a channel's linked discussion group so images show as "comments"** under a channel
  post. Tried and rejected for now: it requires the target channel to have a discussion group
  linked (`getChat`'s `linked_chat_id`), which the chat tested against didn't have, and would also
  need polling for Telegram's auto-forwarded copy of the channel post to reply into. Left for a
  later iteration if a channel with a linked discussion group is the actual target.

## Technical Notes

- **New runtime dependency:** `requests`.
- **Why "log and continue" instead of the pipeline's usual "any error aborts the run"** (AC8 of
  extraction-pipeline.md): a failed upload is a delivery problem for an artifact that's already
  safely on disk, not a sign the run's own output is untrustworthy. See
  [ADR 014](../../decisions/014-telegram-upload-as-pipeline-stage.md) Decision 4. This makes
  `Uploader.upload_all` the **only** step in the pipeline whose exceptions don't propagate past it
  in the ordinary case — worth remembering when reading `run`'s error-handling as a whole.
- **Why a direct HTTP call instead of `python-telegram-bot`:** see
  [ADR 014](../../decisions/014-telegram-upload-as-pipeline-stage.md) Decision 3 / Option B.
- **Why `upload_all(image_paths, source)` instead of a per-image `upload(image_path)`** (the
  original shape — see [ADR 015](../../decisions/015-telegram-album-and-link-delivery.md)): the
  source-link-plus-reply-album delivery only makes sense as one batch operation across every
  image, not as N independent per-image calls each unaware of the others. Error handling moved
  with it: `pipeline.run` no longer loops per image (AC6b replaces the old per-image try/except);
  partial-failure granularity (which album failed, how many images that cost) is now
  `TelegramUploader`'s own concern (AC6), not the generic pipeline's.
- Credential resolution (flag, then env var) happens in two places for different reasons: the CLI
  (AC9) needs it to fail fast with `parser.error` before anything runs; `TelegramUploader` (AC2)
  needs it so a direct Python caller (tests, `run_real_video.py`, playground) gets the same
  behavior without going through the CLI at all.
- **Why check the JSON `"ok"` field instead of trusting the HTTP status alone:** confirmed
  necessary by live testing — Telegram returned HTTP 400 for `createForumTopic` on a non-forum
  chat with a useful `description` in the body (`"Bad Request: the chat is not a forum"`), and a
  library that only checked `raise_for_status()` would still work by accident there, but relying on
  the JSON body's `ok`/`description` gives a real error message instead of a generic
  "400 Client Error" either way.

## Open Questions

Resolved by the user (2026-09-18):

- Q1: Should an upload failure abort the run, or log and continue? **Log and continue** (AC6,
  AC6b) — a departure from the pipeline's usual error propagation, documented in
  [ADR 014](../../decisions/014-telegram-upload-as-pipeline-stage.md) Decision 4.
- Q2: What happens when `clean_method=None` and `save_high_res=True` produces many frames per
  meme instead of one? **Upload exactly what `saved` already contains** (AC5) — no separate
  thinning or selection logic.
- Q3: Standalone command or pipeline stage? **Pipeline stage** — see
  [ADR 014](../../decisions/014-telegram-upload-as-pipeline-stage.md) Decision 1 / Option A.

## Changelog

- 2026-09-18: The user asked how to organize a new module for uploading extracted memes to a
  messenger chat, wanting it kept compact in the same repo. Explored the existing package/spec/ADR
  conventions, drafted a plan (Telegram, as a separate command), then the user changed direction
  mid-review to a pipeline stage instead — one `extract-memes` run both extracts and delivers.
  Drafted this spec; Q1 and Q2 were put to the user and resolved before moving straight to `ready`,
  same as [no-images](no-images.md) did. Wrote
  [ADR 014](../../decisions/014-telegram-upload-as-pipeline-stage.md) for the pipeline-stage
  decision, the direct-HTTP-vs-library choice, and the log-and-continue error handling.
- 2026-09-18: Implemented.
  - **Library:** `src/extract_memes/uploader.py` (`Uploader` ABC, AC1) and
    `src/extract_memes/telegram_uploader.py` (`TelegramUploader`, AC2). `pipeline.run` gained
    `uploader`/`upload_to`/`telegram_bot_token`/`telegram_chat_id` (AC3), constructs a
    `TelegramUploader` up front when `uploader is None and upload_to == "telegram"` (AC4), uploads
    the final `saved` list in order right before returning (AC5), catches and logs a per-image
    upload failure without aborting the run (AC6), and rejects `no_images=True` combined with any
    uploader as a "nothing to upload" `ValueError` (AC7). The upload loop reuses the existing
    `tqdm` progress-bar convention (`desc="Uploading memes"`).
  - **CLI:** `--upload-to {telegram}`, `--telegram-bot-token`, `--telegram-chat-id` (AC8); `main()`
    pre-checks credential resolution and the `--no-images` conflict with `parser.error` before
    calling `pipeline.run` (AC9, AC10).
  - **Dependency:** `requests`, added to `[project.dependencies]` in `pyproject.toml`.
  - **Tests:** `tests/test_uploader.py` (AC11), `tests/test_telegram_uploader.py` (AC12, mocks
    `requests.post`), new cases in `tests/test_pipeline.py` (AC13) and `tests/test_cli.py` (AC14).
  - **Verified:** `pytest -m "not slow"` — 179 passed, no test hits the network or a real Telegram
    endpoint. Manually ran `extract-memes sample/short.mp4 --upload-to telegram
    --telegram-bot-token bogus-token --telegram-chat-id bogus-chat`: both memes were extracted,
    each upload attempt hit the real Telegram API and failed with a genuine `404` (bad token), both
    failures were logged individually plus a `2 of 2 uploads failed.` summary, and the run still
    returned both saved paths. Also confirmed `extract-memes sample/short.mp4 --upload-to telegram`
    with no credentials anywhere exits 2 via `parser.error` before any download starts.

  All ACs are checked. Status `implemented`.
- 2026-09-18: The user ran a real end-to-end test against `https://www.youtube.com/watch?v=i3EC19EcmGs`
  with real Telegram credentials for `@durnev_minus_1`. All 3 uploads failed with `403 Forbidden`
  (the bot lacked posting rights on the chat at the time); the extraction half worked correctly
  regardless, confirming AC6b's "log and continue" behavior for real. The user then asked for the
  memes to be grouped under one "thread/post" with the video link first, to compare against a real
  forum topic. Explored live, outside the shipped code (throwaway scripts, not committed): a
  `createForumTopic` call failed (`the chat is not a forum`); a `sendMessage` (link) followed by a
  `sendMediaGroup` reply (album) succeeded — this is what AC6 implements. Also explored (and
  rejected, both now recorded in Out of Scope): publishing memes to Telegraph
  (`telegra.ph/upload` returns `"Unknown error"` for every image, confirmed with a trivial test
  image via raw `curl`, unrelated to this codebase) and posting as channel-post "comments" (the
  channel has no linked discussion group). The user also asked to chunk into multiple albums past
  Telegram's 10-photo `sendMediaGroup` limit. Once the album approach was confirmed working live,
  the user asked to build it into the pipeline as the real, permanent behavior (not a one-off
  script), replacing the original per-image `upload()`.
  - Redesigned `Uploader.upload_all(image_paths, source)` to replace the per-image `upload()`
    (AC1); `TelegramUploader.upload_all` (AC2, AC6) posts `source` then chunked reply albums.
    `pipeline.run` now calls `upload_all` once instead of looping per image (AC5, AC6b).
  - Wrote [ADR 015](../../decisions/015-telegram-album-and-link-delivery.md) for this redesign.
  - Rewrote `tests/test_uploader.py`, `tests/test_telegram_uploader.py`, and the uploader-related
    cases in `tests/test_pipeline.py` for the new interface (AC11–AC13); `tests/test_cli.py` was
    unchanged since the CLI's flags and `pipeline.run` call signature didn't move.
  - **Verified:** `pytest -m "not slow"` — 180 passed, still no network access in the offline
    suite. All ACs re-checked against the new behavior. Status remains `implemented`.
