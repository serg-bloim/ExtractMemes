"""Deliver a run's saved meme images somewhere other than local disk."""

from abc import ABC, abstractmethod
from pathlib import Path

from extract_memes.downloader import SourceInfo


class Uploader(ABC):
    """Delivers a run's saved meme images somewhere (a messenger chat, etc.)."""

    @abstractmethod
    def upload_all(self, image_paths: list[Path], source: str, info: SourceInfo | None = None) -> str | None:
        """Deliver every image in `image_paths`; return a link to the message that carries them, if there is one.

        `source` is the pipeline's video source (URL or local path), given for context (e.g. to
        post alongside the images). Raises if any part of the delivery failed.
        """
