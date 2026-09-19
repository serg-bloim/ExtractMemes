---
title: "Send Timecodes to a Separate Messenger Channel"
status: implemented
created: 2026-09-19
updated: 2026-09-19
author: ""
depends-on: ["meme-timecodes", "meme-upload"]
---

# Send Timecodes to a Separate Messenger Channel

## Problem Statement

A run can already write a local `timecodes.txt` (`--save-timecodes`) and can already deliver the
extracted meme images to a Telegram chat (`--upload-to telegram`). Neither gets the timecode list
itself in front of anyone without a manual copy-paste. A user who wants the timecodes to land in a
messenger channel — separate from wherever the images go — has no way for one `extract-memes`
invocation to do that.

## Amends

This is an iteration spec, layered on [extraction-pipeline](extraction-pipeline.md),
[meme-timecodes](meme-timecodes.md), and [meme-upload](meme-upload.md). It applies only when
sending is requested (`send_timecodes_to="telegram"` / `--send-timecodes-to telegram`); a run
without it is unchanged in every respect.

| Earlier spec | Criterion | Amended by |
|---|---|---|
| [extraction-pipeline](extraction-pipeline.md) | AC1: `pipeline.run`'s parameter list | AC1 |
| [meme-timecodes](meme-timecodes.md) | the `no_images` branch only builds its scan-timestamp timecode list `if save_timecodes` | AC4 |
| [meme-upload](meme-upload.md) | AC7's "nothing would be saved" list (`save_timecodes`/`save_low_res`/`save_frames`) | AC5 adds `send_timecodes_to` as a further satisfying reason; the existing `uploader is not None` rejection is untouched |
| [meme-upload](meme-upload.md) | AC8: the CLI's flag list | AC9 |

## User Story

**Primary:**
As a user running `extract-memes` against a video, I want the run's timecodes posted to a
Telegram chat separate from the one the meme images go to, so that a channel dedicated to
timecodes/chapters stays up to date without a manual step.

## Acceptance Criteria

### Library: `pipeline.run` / `TimecodeSender`

- [x] AC1: `src/extract_memes/timecode_sender.py` defines `class TimecodeSender(ABC)` with one
      abstract method `send(self, timecodes: list[str], source: str) -> None` (raises only if
      delivery couldn't be attempted at all; implementations should log and keep going past a
      single step's failure where possible).
- [x] AC2: `src/extract_memes/telegram_timecode_sender.py` defines
      `TelegramTimecodeSender(TimecodeSender)`.
      `__init__(self, bot_token: str | None = None, chat_id: str | None = None)` resolves
      `bot_token` from the argument, then `TELEGRAM_BOT_TOKEN` (the same bot as image uploads);
      resolves `chat_id` from the argument, then `TELEGRAM_TIMECODES_CHAT_ID` (a separate chat
      from image uploads); raises `ValueError` immediately if either is still unresolved.
- [x] AC3: `TelegramTimecodeSender.send(timecodes, source)`: an empty `timecodes` list makes no
      request at all. Otherwise it posts `source` as one `sendMessage`, then posts a second
      `sendMessage` replying to it (`reply_to_message_id`) whose text is
      `"\n".join(timecodes)`. If posting the source message fails, the timecode message still
      sends, just without a reply-to (mirrors [meme-upload](meme-upload.md) AC6). A failure
      posting the source message is caught and printed as
      `Failed to post the source link: <error>`; a failure posting the timecode message is caught
      and printed as `Failed to post timecodes: <error>`. Neither raises out of `send` in the
      ordinary case. Talks to the Bot API the same way `TelegramUploader` does: over `requests`,
      treating a response whose JSON body has `"ok": false` as a failure, not just a non-2xx HTTP
      status.
- [x] AC4: `pipeline.run` gains three trailing keyword parameters:
      `timecode_sender: TimecodeSender | None = None`,
      `send_timecodes_to: Literal["telegram"] | None = None`, `timecode_chat_id: str | None = None`.
      No new bot-token parameter — `telegram_bot_token` (already a parameter) is reused for
      `TelegramTimecodeSender` too, since it's the same bot. If `timecode_sender` is `None` and
      `send_timecodes_to == "telegram"`, `run` constructs
      `TelegramTimecodeSender(bot_token=telegram_bot_token, chat_id=timecode_chat_id)` before
      creating any run directory or starting any download — a `ValueError` from that construction
      propagates immediately, same as `TelegramUploader`'s equivalent check.
      The `no_images` branch's timecode-list construction (previously gated on `save_timecodes`
      alone, per [meme-timecodes](meme-timecodes.md) AC3) is now gated on
      `save_timecodes or timecode_sender is not None`, so either flag triggers building the
      scan-timestamp-based list once; `save_timecodes` still controls whether `timecodes.txt` is
      written, and `timecode_sender is not None` (independently) controls whether it's sent —
      either, both, or neither can be set.
      In the ordinary (non-`no_images`) extraction path, the existing `timecodes` list (built
      unconditionally during the extraction loop per meme-timecodes) is what's sent.
- [x] AC5: If `timecode_sender` is not `None` after AC4, `run` calls
      `timecode_sender.send(timecodes, source)` exactly once — for a `no_images=True` run, right
      before returning `[]`; otherwise, after the extraction loop, regardless of whether
      `save_timecodes` also runs and independent of whether `uploader` also runs. `source` is
      `run`'s own `source` argument, unchanged. An exception that escapes `send` does not abort
      the run: it's caught and printed as `Timecode send failed: <error>`, and the run finishes
      normally (same log-and-continue philosophy as `Uploader.upload_all`, per
      [ADR 014](../../decisions/014-telegram-upload-as-pipeline-stage.md) Decision 4).
- [x] AC6: `no_images=True` combined with `timecode_sender is not None` (or
      `send_timecodes_to is not None`) is **allowed** — unlike the image `uploader`, there's
      something to send even with no images: the scan-timestamp-based timecode list. The existing
      `no_images=True` + `uploader is not None` rejection (meme-upload AC7) is unchanged.
- [x] AC7: With `no_images=True`, the existing "nothing would be saved" check
      (previously: at least one of `save_timecodes`/`save_low_res`/`save_frames`) now also treats
      `timecode_sender is not None` (equivalently, `send_timecodes_to` set) as a satisfying
      reason — so `no_images=True, send_timecodes_to="telegram"` alone, with no other save flag,
      does not raise.

### CLI

- [x] AC8: `src/extract_memes/__main__.py` adds:
      - `--send-timecodes-to` (choices `telegram`, default `None`): post the run's timecodes to a
        messenger chat as the run finishes.
      - `--timecode-chat-id` (default `None`): falls back to `TELEGRAM_TIMECODES_CHAT_ID`.

      Both are passed straight through to `pipeline.run` as `send_timecodes_to`,
      `timecode_chat_id`; the existing `--telegram-bot-token` (and `TELEGRAM_BOT_TOKEN` fallback)
      is reused, not duplicated.
- [x] AC9: With `--send-timecodes-to telegram` given, `main()` resolves the bot token and
      timecode chat id the same way `TelegramTimecodeSender` does (flag, then env var) and calls
      `parser.error(...)` — exit code 2, before `pipeline.run` is called at all — if either is
      still missing.
- [x] AC10: `--send-timecodes-to telegram --no-images` is **not** rejected by the CLI — this
      combination is meant to work (contrast [meme-upload](meme-upload.md) AC10, which does
      reject `--upload-to telegram --no-images`).

### Tests

- [x] AC11: `tests/test_timecode_sender.py`: a fake concrete `TimecodeSender` records each `send`
      call (timecodes and source); the ABC cannot be instantiated directly.
- [x] AC12: `tests/test_telegram_timecode_sender.py`: `requests.post` is mocked (never hits the
      network). Covers: the source is posted via `sendMessage` before the timecode reply; the
      reply is a second `sendMessage` with `reply_to_message_id` set to the source message's id
      and `text = "\n".join(timecodes)`; an empty `timecodes` makes no requests at all; a failed
      source message still lets the timecode reply send, without a reply-to; a failed timecode
      reply is logged and doesn't raise; missing bot token/chat id (no args, no env vars) raises
      `ValueError` before any request; env var fallback works for both `TELEGRAM_BOT_TOKEN` and
      `TELEGRAM_TIMECODES_CHAT_ID` independently.
- [x] AC13: `tests/test_pipeline.py`: a fake `TimecodeSender` passed as `timecode_sender=`
      receives exactly one `send(timecodes, source)` call, with the same list `save_timecodes`
      would have written. A run with no `timecode_sender` never constructs or calls one. A fake
      sender whose `send` raises still lets the run finish, still returns the full `saved` list,
      and `Timecode send failed: <error>` is captured with `capsys`. `no_images=True` with
      `timecode_sender` set (no `save_timecodes`) returns `[]` without raising and calls `send`
      once with the scan-timestamp-based list. `no_images=True` with none of
      `save_timecodes`/`save_low_res`/`save_frames`/`send_timecodes_to` still raises `ValueError`.
      `no_images=True` with `uploader` set still raises regardless of `timecode_sender`.
- [x] AC14: `tests/test_cli.py`: `--send-timecodes-to telegram` with no credentials anywhere exits
      2 via `parser.error`; with `--telegram-bot-token`/`--timecode-chat-id` (or the env vars set)
      it reaches `pipeline.run` with `send_timecodes_to="telegram"` and `timecode_chat_id` passed
      through; `--send-timecodes-to telegram --no-images` does **not** exit 2.

## Out of Scope

- **Discord, Slack, or any messenger besides Telegram** for timecode delivery — same rationale as
  [meme-upload](meme-upload.md)'s equivalent exclusion for image delivery.
- **A link to the memes-upload post, and a job-run report, as further replies under the same
  source message.** Both were named by the user as the eventual shape (a post whose replies grow
  to include a memes-post link and a run report), but neither exists yet as its own feature; this
  spec only adds the source message and the timecodes reply. The message shape here doesn't
  preclude adding more replies later.
- **Message-length chunking.** A `timecodes` list long enough to exceed Telegram's 4096-character
  message limit is not split or truncated; the `sendMessage` call would simply fail and be logged,
  same as any other delivery failure.
- **Retry/backoff on a failed send.** One attempt per message; a failure is logged, not retried.
- **Dedup or skip-if-already-sent across separate runs of the same video.** Re-running the same
  `run_name` re-sends everything again.

## Technical Notes

- **No new runtime dependency** — reuses `requests`, already a dependency for `TelegramUploader`.
- **Why a separate `TimecodeSender`/`TelegramTimecodeSender` pair instead of a method on
  `TelegramUploader`:** keeps text-sending fully decoupled from image-uploading, mirroring the
  existing `uploader.py`/`telegram_uploader.py` module-pair convention (and `FrameClassifier`'s)
  rather than growing `TelegramUploader` a second, unrelated responsibility. This was an explicit
  choice, not a default — see the spec's Changelog.
- **Why log-and-continue, and why check the JSON `"ok"` field instead of trusting HTTP status
  alone:** both already decided for image uploads — see
  [ADR 014](../../decisions/014-telegram-upload-as-pipeline-stage.md) Decision 4 and
  [ADR 015](../../decisions/015-telegram-album-and-link-delivery.md). This spec applies the same
  reasoning to timecode delivery rather than re-deciding it; no new ADR was written for that
  reason.
- **Why the same bot but a different chat id:** the user's own framing — this is one bot posting
  to two different destinations (an images channel and a timecodes channel), not two independent
  bot identities.

## Open Questions

Resolved by the user (2026-09-19), via `AskUserQuestion` before drafting:

- Q1: Same bot+chat as image uploads, or something else? **Same bot, a new chat id**
  (`TELEGRAM_TIMECODES_CHAT_ID`/`--timecode-chat-id`), reusing `TELEGRAM_BOT_TOKEN`.
- Q2: Does sending require `--save-timecodes` too? **No** — independent
  `--send-timecodes-to telegram` flag (AC4, AC8).
- Q3: What does the message look like? **Source link as one message, then a reply with the
  timecode list** — the first step of a post whose replies will eventually also carry a memes-post
  link and a job-run report (both out of scope here; see Out of Scope).
- Q4: New `TimecodeSender` ABC, or a method on `TelegramUploader`? **New `TimecodeSender` ABC**
  (AC1, AC2), mirroring `Uploader`/`TelegramUploader`.

## Changelog

- 2026-09-19: The user picked this item off `specs/BACKLOG.md` ("Send timecodes into a separate
  messenger channel."). Explored the existing `meme-timecodes` and `meme-upload` specs, ADR 014,
  and ADR 015 as direct precedent. Put Q1-Q4 to the user via `AskUserQuestion` before drafting;
  their answer to Q3 also revealed two future, not-yet-implemented backlog items (a memes-post-link
  reply, a job-run-report reply) that are recorded here as Out of Scope rather than designed now.
  Drafted this spec directly to `ready`, since all open questions were already resolved.
- 2026-09-19: Implemented.
  - **Library:** `src/extract_memes/timecode_sender.py` (`TimecodeSender` ABC, AC1) and
    `src/extract_memes/telegram_timecode_sender.py` (`TelegramTimecodeSender`, AC2, AC3).
    `pipeline.run` gained `timecode_sender`/`send_timecodes_to`/`timecode_chat_id` (AC4),
    constructs a `TelegramTimecodeSender` up front when `timecode_sender is None and
    send_timecodes_to == "telegram"` (AC4), sends the timecode list once per run — from the
    extraction loop's list normally, from the scan-timestamp list when `no_images=True` (AC5) —
    and allows `no_images=True` together with `timecode_sender`/`send_timecodes_to`, extending the
    "nothing would be saved" check with `timecode_sender is not None` as a further satisfying
    reason (AC6, AC7).
  - **CLI:** `--send-timecodes-to {telegram}`, `--timecode-chat-id` (AC8); `main()` pre-checks
    credential resolution the same way as `--upload-to telegram`, but does not reject
    `--no-images` (AC9, AC10).
  - **Tests:** `tests/test_timecode_sender.py` (AC11), `tests/test_telegram_timecode_sender.py`
    (AC12, mocks `requests.post`), new cases in `tests/test_pipeline.py` (AC13) and
    `tests/test_cli.py` (AC14).
  - **Verified:** `pytest -m "not slow"` — 225 passed, no test hits the network or a real
    Telegram endpoint.

  All ACs are checked. Status `implemented`.
