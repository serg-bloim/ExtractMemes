"""Manual Telegram upload experiments to run from the IDE.

These are pytest-format only so the IDE shows a run icon next to each one; they assert nothing and
post to the real Telegram chat. A bare `pytest` skips this directory (`testpaths` in
pyproject.toml), and the module skips itself unless TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are
set, so an explicit directory run can't fail or post by accident.
"""

import os
from pathlib import Path

import pytest

from extract_memes.downloader import SourceInfo
from extract_memes.telegram_uploader import TelegramUploader

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LABELED_DATASET = PROJECT_ROOT / "data" / "labeled_dataset"

pytestmark = pytest.mark.skipif(
    not (os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID")),
    reason="TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are not set",
)


def test_telegram_upload():
    """Sends a source message plus an album of labeled-set images.

    Use 11+ images to see the album chunking (the limit is 10 per album).
    """
    images = sorted((LABELED_DATASET / "positive").glob("*.png"))[:20]
    print(f"Uploading {len(images)} images")
    info = SourceInfo(
        title="Playground test video",
        thumbnail_url="https://i.ytimg.com/vi/0TSqnhLXYfA/hqdefault.jpg",
    )
    TelegramUploader().upload_all(images, "https://example.com/playground-telegram-test", info)


if __name__ == "__main__":
    test_telegram_upload()
