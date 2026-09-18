"""Deliver a run's saved meme images somewhere other than local disk."""

from abc import ABC, abstractmethod
from pathlib import Path


class Uploader(ABC):
    """Delivers a run's saved meme images somewhere (a messenger chat, etc.)."""

    @abstractmethod
    def upload_all(self, image_paths: list[Path], source: str) -> None:
        """Deliver every image in `image_paths`.

        `source` is the pipeline's video source (URL or local path), given for context (e.g. to
        post alongside the images). Raises only if delivery couldn't be attempted at all;
        implementations should log and keep going past a single item's failure where possible,
        rather than losing everything else over one bad item.
        """
