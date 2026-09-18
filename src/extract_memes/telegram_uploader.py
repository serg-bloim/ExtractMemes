"""Upload meme images to a Telegram chat: a source-link message, then chunked photo albums."""

import json
import os
from pathlib import Path

import requests

from extract_memes.uploader import Uploader

ALBUM_LIMIT = 10
"""Telegram's `sendMediaGroup` accepts at most 10 items per call."""


def _chunks(items: list[Path], size: int) -> list[list[Path]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


class TelegramUploader(Uploader):
    """Posts `source` as one message, then every image as a reply, in albums of up to 10."""

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

    def _call(self, method: str, **kwargs) -> dict:
        url = f"{self.BASE_URL.format(token=self.bot_token)}/{method}"
        response = requests.post(url, timeout=30.0, **kwargs)
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram {method} failed: {data.get('description', response.text)}")
        return data

    def upload_all(self, image_paths: list[Path], source: str) -> None:
        if not image_paths:
            return

        reply_to: int | None = None
        try:
            result = self._call("sendMessage", data={"chat_id": self.chat_id, "text": source})
            reply_to = result["result"]["message_id"]
        except Exception as exc:
            print(f"Failed to post the source link: {exc}")

        failed = 0
        for batch in _chunks(image_paths, ALBUM_LIMIT):
            try:
                self._send_album(batch, reply_to)
            except Exception as exc:
                failed += len(batch)
                names = ", ".join(path.name for path in batch)
                print(f"Upload failed for {names}: {exc}")
        if failed:
            print(f"{failed} of {len(image_paths)} uploads failed.")

    def _send_album(self, batch: list[Path], reply_to: int | None) -> None:
        opened = [open(path, "rb") for path in batch]
        try:
            files = {f"photo{i}": (path.name, file) for i, (path, file) in enumerate(zip(batch, opened))}
            media = [{"type": "photo", "media": f"attach://photo{i}"} for i in range(len(batch))]
            data = {"chat_id": self.chat_id, "media": json.dumps(media)}
            if reply_to is not None:
                data["reply_to_message_id"] = reply_to
            self._call("sendMediaGroup", data=data, files=files)
        finally:
            for file in opened:
                file.close()
