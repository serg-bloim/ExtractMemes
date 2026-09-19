"""Deliver a run's timecodes somewhere other than local disk."""

from abc import ABC, abstractmethod


class TimecodeSender(ABC):
    """Delivers a run's timecode list somewhere (a messenger chat, etc.)."""

    @abstractmethod
    def send(self, timecodes: list[str], source: str) -> None:
        """Deliver every line in `timecodes`.

        `source` is the pipeline's video source (URL or local path), given for context (e.g. to
        post alongside the timecodes as a source-link message). Raises only if delivery couldn't
        be attempted at all; implementations should log and keep going past a single step's
        failure where possible, rather than losing everything else over one bad step.
        """
