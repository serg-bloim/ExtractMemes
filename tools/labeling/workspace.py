"""Which video the labeler has open, and loading another one in the background."""

import re
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from . import dataset as dataset_module

if TYPE_CHECKING:
    from .server import LabelerApp

Progress = Callable[[str, float | None], None]
Opener = Callable[[str, str | None, Progress], "LabelerApp"]
Inspector = Callable[[str], dict]

_FORMAT_ID = re.compile(r"[\w.-]+")  # a plain format id, never a yt-dlp format expression


class NoVideoError(RuntimeError):
    """No video is open yet."""


class BusyError(RuntimeError):
    """A video is already being loaded."""


class Workspace:
    """Holds the open `LabelerApp` and the progress of loading the next one.

    `opener(source, format_id, progress)` builds a `LabelerApp` (downloading and indexing as needed);
    it runs on a background thread. `inspector(url)` looks a video up without downloading it. The video that is open stays open until the new one is ready, and stays
    open if loading fails.
    """

    def __init__(
        self,
        opener: Opener,
        datasets_dir: Path = dataset_module.DATASETS_DIR,
        initial: "LabelerApp | None" = None,
        inspector: Inspector | None = None,
    ) -> None:
        self._opener = opener
        self._inspector = inspector
        self.datasets_dir = datasets_dir
        self._current: "LabelerApp | None" = initial
        self._status: dict = {"state": "ready" if initial else "idle", "message": "", "progress": None}
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    @classmethod
    def ready(cls, labeler: "LabelerApp", datasets_dir: Path = dataset_module.DATASETS_DIR) -> "Workspace":
        """A workspace with `labeler` already open (opening another video isn't possible)."""

        def refuse(source: str, format_id: str | None, progress: Progress) -> "LabelerApp":
            raise RuntimeError("opening another video is not available here")

        return cls(refuse, datasets_dir, initial=labeler)

    @property
    def current(self) -> "LabelerApp":
        with self._lock:
            if self._current is None:
                raise NoVideoError("no video is open")
            return self._current

    def status(self) -> dict:
        with self._lock:
            current = self._current
            return {
                **self._status,
                "video": current.dataset.video.id if current else None,
                "datasets": dataset_module.list_datasets(self.datasets_dir),
            }

    @staticmethod
    def _video_id(source) -> str:
        if not isinstance(source, str):
            raise ValueError("source must be a YouTube URL or video id")
        try:
            return dataset_module.video_id_from(source.strip())
        except dataset_module.DatasetError as exc:
            raise ValueError(str(exc)) from exc

    def inspect(self, source) -> dict:
        """The video's details and formats, plus its dataset when it has one. Raises `ValueError`."""
        video_id = self._video_id(source)
        if self._inspector is None:
            raise ValueError("looking up videos is not available here")
        try:
            info = self._inspector(dataset_module.canonical_url(video_id))
        except dataset_module.DatasetError as exc:
            raise ValueError(str(exc)) from exc
        info.setdefault("preselected", dataset_module.preferred_format(info.get("formats") or []))
        path = dataset_module.dataset_path(video_id, self.datasets_dir)
        info["dataset"] = None
        if path.is_file():
            dataset = dataset_module.load(path)
            info["dataset"] = {"format_id": dataset.video.format_id, "memes": len(dataset.memes),
                               "not_memes": len(dataset.not_memes)}
        return info

    def open(self, source, format_id=None) -> None:
        """Start loading the video for a YouTube URL or id; raises `ValueError` or `BusyError`.

        `format_id` picks the yt-dlp format for a video with no dataset yet (default: the worst).
        """
        video_id = self._video_id(source)
        if format_id in ("", None):
            format_id = None
        elif not isinstance(format_id, str) or not _FORMAT_ID.fullmatch(format_id):
            raise ValueError("format_id must be a plain yt-dlp format id")
        with self._lock:
            if self._status["state"] == "loading":
                raise BusyError("another video is still loading")
            self._status = {"state": "loading", "message": f"Opening {video_id}", "progress": None}
            self._thread = threading.Thread(target=self._load, args=(video_id, format_id), daemon=True)
            self._thread.start()

    def wait(self, timeout: float | None = None) -> None:
        """Block until the current load finishes (for tests)."""
        if self._thread:
            self._thread.join(timeout)

    def _set_progress(self, message: str, fraction: float | None) -> None:
        with self._lock:
            if self._status["state"] == "loading":
                self._status = {"state": "loading", "message": message, "progress": fraction}

    def _load(self, video_id: str, format_id: str | None) -> None:
        try:
            # The page only supplies an id; the URL is always built here.
            labeler = self._opener(dataset_module.canonical_url(video_id), format_id, self._set_progress)
        except Exception as exc:
            with self._lock:
                self._status = {"state": "error", "message": f"Could not open {video_id}: {exc}", "progress": None}
            return
        with self._lock:
            previous, self._current = self._current, labeler
            self._status = {"state": "ready", "message": "", "progress": None}
        if previous is not None:
            previous.close()
