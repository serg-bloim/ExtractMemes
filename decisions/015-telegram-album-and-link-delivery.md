# 015 — Deliver Memes to Telegram as a Link Message Plus Chunked Reply Albums

**Date:** 2026-09-18
**Status:** Accepted

---

## Context

[ADR 014](014-telegram-upload-as-pipeline-stage.md) shipped `Uploader.upload(image_path)`: one
`sendPhoto` call per image, no relationship between them in the chat. The user then ran the
feature against a real bot and a real channel (`@durnev_minus_1`) and asked for more: group the
run's memes under one post, with the source video's link posted first, so a viewer sees where the
memes came from and sees them as one thing rather than N unrelated messages.

Before settling on an approach, three options were tried live against the real channel, outside
the shipped code (throwaway scripts):

1. **A real Telegram forum topic** (`createForumTopic`, then post inside it via
   `message_thread_id`). Failed outright: `Bad Request: the chat is not a forum`. This only works
   when the target chat is a supergroup with Telegram's "Topics" feature turned on — true of some
   chats, not this one, and not something the pipeline can detect or turn on itself.
2. **Publish to Telegraph (telegra.ph) and post the page link.** Telegraph's page-creation API
   works, but its only image-upload path (`telegra.ph/upload` — undocumented; there's no official
   upload endpoint) returned `"Unknown error"` for every attempt, including a trivial 1x1 test PNG
   sent with plain `curl`, outside this codebase entirely. That confirms the endpoint itself is
   broken for API callers generally, not something wrong with our request.
3. **A link message, then the memes as a reply — grouped into one Telegram "album"
   (`sendMediaGroup`, up to 10 photos per call) rather than individual `sendPhoto` calls.**
   Succeeded immediately: works in any chat type (channel, group, or supergroup), no special chat
   configuration needed.

A fourth option — posting as "comments" under a channel post — was also considered, but the
channel in question has no linked discussion group (`getChat` returns no `linked_chat_id`), which
Telegram requires for comments to exist at all. Left for later if the target channel ever has one.

## Decision

1. **Deliver as: one source-link message, then the images as reply albums of up to 10.** A run
   with 3 images makes one album; a run with 12 makes two (10 then 2), chunked in the pipeline
   order `pipeline.run` already produced.
2. **Redesign `Uploader`'s interface from per-image to batch.** `upload(image_path: Path) -> None`
   is replaced by `upload_all(image_paths: list[Path], source: str) -> None`. The old shape doesn't
   fit: posting a link once and grouping images afterward is one operation across the whole set,
   not N independent per-image calls that don't know about each other. There is still only one
   implementation (`TelegramUploader`), so this is a clean redesign, not a breaking change to
   anything depending on the old shape.
3. **Error-handling granularity moves with it.** `pipeline.run` no longer loops per image with its
   own try/except (ADR 014 Decision 4's "log and continue" policy); it calls `upload_all` once and
   catches only a total failure. Partial-failure handling — which album failed, how many images
   that cost — becomes `TelegramUploader`'s own responsibility, since only it knows about albums.
4. **A failed source-link message doesn't block the albums.** If `sendMessage` fails, the albums
   still send, just without `reply_to_message_id` — delivering the images matters more than the
   context message they'd have replied to.
5. **Check the Telegram API's own `"ok"` field, not just the HTTP status.** Confirmed necessary
   during live testing: Telegram does return meaningful HTTP error codes (`400`, `403`, `404` were
   all seen), but reading the JSON body's `description` gives a real, specific error message
   (`"Bad Request: the chat is not a forum"`) instead of a generic `"400 Client Error"`.

## Options Considered

### Option A: Real forum topics (rejected)

Would be the most literal "thread." Rejected: only works on chats explicitly configured as forum
supergroups, which is chat-specific state outside this tool's control, and failed on the very chat
being tested against.

### Option B: Telegraph page with embedded images (rejected)

Would give one clean link instead of N Telegram messages. Rejected: the only image-upload path
(`telegra.ph/upload`) is broken for API callers — confirmed independent of our code with a raw
`curl` test against a trivial image.

### Option C: Link message + chunked reply albums (chosen)

**Chosen:** works in any Telegram chat type with no special configuration, verified live, and
Telegram's own 10-photo `sendMediaGroup` limit is easy to chunk around.

### Option D: Keep per-image `upload()`, add a second batch-oriented method

Considered instead of a full interface redesign, e.g. `upload(image_path)` staying as the ABC
contract with `TelegramUploader` overriding some separate `upload_all` for its own use.

**Rejected:** would leave the ABC's contract (per-image) not matching what any real caller
(`pipeline.run`) actually calls, and there's no second implementation yet needing the old shape to
stay stable. A clean redesign is simpler to read and test than two overlapping methods.

## Consequences

**Positive:**
- Delivered memes read as one thing in the chat — a link, then the pictures — instead of a wall of
  unrelated photo messages.
- Works on any chat type; no dependency on Topics or a linked discussion group being configured.
- Fewer Telegram API calls for a typical run (one link message + one album, vs. one call per
  image), which also means less chance of Telegram-side rate limiting on a large run.

**Negative / costs:**
- **The `Uploader` ABC's contract changed twice within the same feature's life** (per-image, then
  batch) — a reader checking git history sees churn that a slower rollout wouldn't have had. Worth
  it here because both shapes were tried against a real chat before committing to one, rather than
  guessed at.
- **A run with many memes still makes multiple albums**, each its own reply to the same link
  message rather than one single thread the way a real forum topic would render them. Acceptable:
  it was the fallback specifically because forum topics don't work on every chat.
- **No dedup/skip-if-already-posted still applies** (unchanged from ADR 014) — re-running the same
  `run_name` posts a new link message and new albums again.

## References

- [meme-upload spec](../specs/features/meme-upload.md): AC6 (album/reply mechanics), AC6b (the
  pipeline-level "log and continue" boundary that replaces the old per-image loop).
- [ADR 014](014-telegram-upload-as-pipeline-stage.md): the original pipeline-stage decision and
  per-image `Uploader.upload` shape this ADR redesigns.
