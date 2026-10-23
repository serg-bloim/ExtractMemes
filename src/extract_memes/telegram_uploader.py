"""Upload meme images to a Telegram chat: a source-link message, then chunked photo albums."""

import json
import os
import time
from pathlib import Path

import cv2
import numpy as np
import requests

from extract_memes.downloader import SourceInfo
from extract_memes.uploader import Uploader

ALBUM_LIMIT = 10
"""Telegram's `sendMediaGroup` accepts at most 10 items per call."""
CAPTION_LIMIT = 1024
"""Telegram's maximum photo caption length."""
DISCUSSION_WAIT_SECONDS = 30.0
"""How long to wait for Telegram to auto-forward the channel post into its discussion group."""
POLL_SECONDS = 3
"""Long-poll timeout of each `getUpdates` call while waiting for that forward."""
CALL_TIMEOUT = 5.0
"""Timeout of an ordinary Bot API call."""
ALBUM_TIMEOUT = (10.0, 120.0)
"""(connect, read) timeout of `sendMediaGroup`, which uploads the images themselves."""
ALBUM_ATTEMPTS = 3
"""How many times an album is tried when the request times out, drops, or is rate limited."""
RETRY_BACKOFF_SECONDS = 5.0
"""Base wait before retrying an album; doubles each attempt."""
JPEG_QUALITY = 90
"""Quality of the JPEG copy sent in place of each PNG."""


class _RateLimited(RuntimeError):
    def __init__(self, message: str, retry_after: float) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def _as_jpeg_bytes(name: str, raw: bytes) -> tuple[str, bytes]:
    """The image as `(file name, bytes)`, re-encoded to JPEG; the original when it can't be decoded."""
    image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if image is not None:
        ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        if ok:
            return Path(name).with_suffix(".jpg").name, encoded.tobytes()
    return name, raw


def _chunks(items: list[Path], size: int) -> list[list[Path]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


class TelegramUploader(Uploader):
    """Posts `source` (with the video's thumbnail and title, when known) as one message, then every image under it, in albums of up to 10.

    When the chat is a channel with a linked discussion group, the albums go there as comments on the
    post; otherwise they reply to the post in the chat. Any failure (the post, the comments thread, an
    album) raises `RuntimeError`, so the caller can treat the whole upload as failed.
    """

    BASE_URL = "https://api.telegram.org/bot{token}"

    def __init__(self, bot_token: str | None = None, chat_id: str | None = None) -> None:
        bot_token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN")
        chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
        if not bot_token or not chat_id:
            raise ValueError(
                "Telegram bot token and chat id are required: pass bot_token/chat_id, or set "
                "TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID"
            )
        self.bot_token = bot_token
        self.chat_id = chat_id

    def _call(self, method: str, timeout: float | tuple[float, float] = CALL_TIMEOUT, **kwargs) -> dict:
        url = f"{self.BASE_URL.format(token=self.bot_token)}/{method}"
        response = requests.post(url, timeout=timeout, **kwargs)
        data = response.json()
        if not data.get("ok"):
            retry_after = (data.get("parameters") or {}).get("retry_after")
            if data.get("error_code") == 429 and retry_after is not None:
                raise _RateLimited(f"Telegram {method} failed: {data.get('description')}", float(retry_after))
            raise RuntimeError(f"Telegram {method} failed: {data.get('description', response.text)}")
        return data

    def _post_parent(self, source: str, info: SourceInfo | None) -> int:
        """Post the parent message, trying thumbnail+title, then title, then the bare link.

        Returns its message id; raises `RuntimeError` if every attempt failed.
        """
        title = info.title if info else None
        text = f"{title}\n{source}" if title else source
        attempts: list[tuple[str, dict]] = []
        if info and info.thumbnail_url:
            caption = text if len(text) <= CAPTION_LIMIT else f"{title[: CAPTION_LIMIT - len(source) - 1]}\n{source}"
            attempts.append(("sendPhoto", {"photo": info.thumbnail_url, "caption": caption}))
        if title:
            attempts.append(("sendMessage", {"text": text}))
        attempts.append(("sendMessage", {"text": source}))

        last_error: Exception | None = None
        for method, fields in attempts:
            try:
                result = self._call(method, data={"chat_id": self.chat_id, **fields})
                return result["result"]["message_id"]
            except Exception as exc:
                print(f"Failed to post the source link: {exc}")
                last_error = exc
        raise RuntimeError(f"Could not post the source link: {last_error}")

    def upload_all(self, image_paths: list[Path], source: str, info: SourceInfo | None = None) -> None:
        if not image_paths:
            return

        reply_to = self._post_parent(source, info)
        target_chat, thread = self.chat_id, reply_to
        comments = self._comments_thread(reply_to)
        if comments:
            target_chat, thread = comments

        for batch in _chunks(image_paths, ALBUM_LIMIT):
            try:
                self._send_album(batch, target_chat, thread)
            except Exception as exc:
                names = ", ".join(path.name for path in batch)
                raise RuntimeError(f"Upload failed for {names}: {exc}") from exc

    def _comments_thread(self, post_id: int) -> tuple[int, int] | None:
        """Return `(discussion chat id, forwarded post id)` for the comments of channel post `post_id`.

        `None` when the chat has no linked discussion group. Raises `RuntimeError` if the chat can't be
        looked up, the updates can't be read, or the forwarded copy never shows up. The bot must be an
        admin of the discussion group to see the forward in `getUpdates`.
        """
        try:
            chat = self._call("getChat", data={"chat_id": self.chat_id})["result"]
        except Exception as exc:
            raise RuntimeError(f"Could not look up the chat's discussion group: {exc}") from exc
        linked = chat.get("linked_chat_id")
        if not linked:
            return None

        deadline = time.monotonic() + DISCUSSION_WAIT_SECONDS
        offset: int | None = None
        while True:
            params = {"timeout": POLL_SECONDS, "allowed_updates": json.dumps(["message"])}
            if offset is not None:
                params["offset"] = offset
            try:
                updates = self._call("getUpdates", data=params)["result"]
            except Exception as exc:
                raise RuntimeError(f"Could not read the discussion group's updates: {exc}") from exc
            for update in updates:
                offset = update["update_id"] + 1
                message = update.get("message", {})
                origin = message.get("forward_origin", {})
                if (
                    message.get("is_automatic_forward")
                    and message.get("chat", {}).get("id") == linked
                    and origin.get("chat", {}).get("id") == chat["id"]
                    and origin.get("message_id") == post_id
                ):
                    return linked, message["message_id"]
            if time.monotonic() >= deadline:
                raise RuntimeError("The post's comments thread never appeared")

    def _send_album(self, batch: list[Path], chat_id: str | int, reply_to: int | None) -> None:
        for attempt in range(1, ALBUM_ATTEMPTS + 1):
            try:
                self._send_album_once(batch, chat_id, reply_to)
                return
            except (requests.Timeout, requests.ConnectionError, _RateLimited) as exc:
                if attempt == ALBUM_ATTEMPTS:
                    raise
                wait = exc.retry_after if isinstance(exc, _RateLimited) else RETRY_BACKOFF_SECONDS * 2 ** (attempt - 1)
                print(f"Album upload attempt {attempt} failed ({exc}); retrying in {wait:g}s")
                time.sleep(wait)

    def _send_album_once(self, batch: list[Path], chat_id: str | int, reply_to: int | None) -> None:
        files = {}
        for i, path in enumerate(batch):
            with open(path, "rb") as file:
                files[f"photo{i}"] = _as_jpeg_bytes(path.name, file.read())
        media = [{"type": "photo", "media": f"attach://photo{i}"} for i in range(len(batch))]
        data = {"chat_id": chat_id, "media": json.dumps(media)}
        if reply_to is not None:
            data["reply_to_message_id"] = reply_to
        self._call("sendMediaGroup", timeout=ALBUM_TIMEOUT, data=data, files=files)
