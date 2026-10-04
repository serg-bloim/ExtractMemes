"""Manual Telegram upload experiments to run from the IDE.

The functions are named `test_*` only so IDE pytest integrations show a run icon next to each one.
They are not tests: they assert nothing. They post to the real Telegram chat, so
TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in the environment. This file's name doesn't
match pytest's `test_*.py` / `*_test.py` collection patterns, so running `pytest` from the project
root collects nothing from here.
"""

from pathlib import Path

from extract_memes.telegram_uploader import TelegramUploader

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LABELED_DATASET = PROJECT_ROOT / "data" / "labeled_dataset"


def test_telegram_upload():
    """Sends a source message plus an album of labeled-set images.

    Use 11+ images to see the album chunking (the limit is 10 per album).
    """
    images = sorted((LABELED_DATASET / "positive").glob("*.png"))[:20]
    print(f"Uploading {len(images)} images")
    TelegramUploader().upload_all(images, "https://example.com/playground-telegram-test")


if __name__ == "__main__":
    test_telegram_upload()
