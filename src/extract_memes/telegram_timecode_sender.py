"""Send a run's timecodes to a Telegram chat: a source-link message, then a reply with the list."""

import os

import requests

from extract_memes.timecode_sender import TimecodeSender


class TelegramTimecodeSender(TimecodeSender):
    """Posts `source` as one message, then the timecode list as a reply to it."""

    BASE_URL = "https://api.telegram.org/bot{token}"

    def __init__(self, bot_token: str | None = None, chat_id: str | None = None) -> None:
        bot_token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN")
        chat_id = chat_id or os.environ.get("TELEGRAM_TIMECODES_CHAT_ID")
        if not bot_token or not chat_id:
            raise ValueError(
                "Telegram bot token and timecode chat id are required: pass bot_token/chat_id, "
                "or set TELEGRAM_BOT_TOKEN/TELEGRAM_TIMECODES_CHAT_ID"
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

    def send(self, timecodes: list[str], source: str) -> None:
        if not timecodes:
            return

        reply_to: int | None = None
        try:
            result = self._call("sendMessage", data={"chat_id": self.chat_id, "text": source})
            reply_to = result["result"]["message_id"]
        except Exception as exc:
            print(f"Failed to post the source link: {exc}")

        data = {"chat_id": self.chat_id, "text": "\n".join(timecodes)}
        if reply_to is not None:
            data["reply_to_message_id"] = reply_to
        try:
            self._call("sendMessage", data=data)
        except Exception as exc:
            print(f"Failed to post timecodes: {exc}")
