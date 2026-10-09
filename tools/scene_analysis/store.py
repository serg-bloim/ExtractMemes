"""The scene database: one YAML file, reached only through `SceneStore`.

Nothing else reads or writes the file. Every write is atomic (temp file, flush to disk, rename), keeps
the previous version as `<file>.bak`, and is serialized with other writers by a lock file. A file that
does not parse or does not fit the schema is refused rather than overwritten.
"""

import contextlib
import copy
import fcntl
import os
import shutil
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from enum import IntEnum
from typing import Any
from datetime import datetime, timezone
from time import perf_counter
from pathlib import Path

import yaml

DEFAULT_PATH = Path("data/datasets/scene_analysis/scene_analysis.yaml")
VERSION = 2
VERDICTS = ("meme", "not_meme", "unsure")
CHECKS = ("miss", "false_positive")

_SCENE_FIELDS = {"first_frame": int, "last_frame": int, "start_ts": (int, float), "end_ts": (int, float), "frame_count": int}
_STATS_FIELDS = ("op", "threshold", "min", "max", "mean", "std", "share_flagged")
_NUMERIC_STATS = _STATS_FIELDS[1:]
_CLAUDE_FIELDS = ("verdict", "reason", "check", "checked_at")

Scene = dict


class Status(IntEnum):
    """HTTP-style status codes returned by every operation."""

    OK = 200  # done; something changed (or the data was read)
    CREATED = 201  # a new scene, criterion or status was added
    NO_CONTENT = 204  # valid, but nothing changed
    BAD_REQUEST = 400  # an argument is invalid
    NOT_FOUND = 404  # no such scene
    CONFLICT = 409  # a scene already starts at that frame, or the new one overlaps another
    SERVER_ERROR = 500  # the database file is unreadable or doesn't match the schema


@dataclass
class Response:
    """What an operation returns: a `status`, a `message` for anything but success, and `data` for reads."""

    status: Status
    message: str = ""
    data: Any = None

    @property
    def ok(self) -> bool:
        return self.status < 300


class SceneStoreError(RuntimeError):
    """The database file is unreadable or does not match the schema (reported as 500)."""


class InvalidInputError(SceneStoreError):
    """An argument is invalid (reported as 400)."""


def _plain(value):
    """`value` as plain YAML data: numpy scalars become Python numbers."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if hasattr(value, "item") and callable(value.item):
        return value.item()
    return value


def _check_stats(criterion: str, stats: dict) -> dict:
    """Validate one criterion's stats. `op`, `threshold` and `share_flagged` are all null for a criterion with no condition."""
    stats = _plain(stats)
    if set(stats) != set(_STATS_FIELDS):
        raise InvalidInputError(f"stats of {criterion!r} must have exactly {', '.join(_STATS_FIELDS)}; got {sorted(stats)}")
    conditional = ("op", "threshold", "share_flagged")
    if all(stats[name] is None for name in conditional):
        required = [n for n in _NUMERIC_STATS if n not in conditional]
    else:
        required = list(_NUMERIC_STATS)
        if not isinstance(stats["op"], str):
            raise InvalidInputError(f"stats of {criterion!r}: op must be a string")
    for name in required:
        if isinstance(stats[name], bool) or not isinstance(stats[name], (int, float)) or stats[name] != stats[name]:
            raise InvalidInputError(f"stats of {criterion!r}: {name} must be a number, not {stats[name]!r}")
    return stats


def _check_scene(scene: object, where: str = "scene") -> Scene:
    if not isinstance(scene, dict):
        raise InvalidInputError(f"{where} is not a mapping")
    for name, kind in _SCENE_FIELDS.items():
        value = scene.get(name)
        if isinstance(value, bool) or not isinstance(value, kind):
            raise InvalidInputError(f"{where}: {name} is missing or invalid ({value!r})")
    if scene["first_frame"] > scene["last_frame"]:
        raise InvalidInputError(f"{where}: first_frame is after last_frame")
    if not isinstance(scene.get("stats"), dict):
        raise InvalidInputError(f"{where}: stats must be a mapping")
    for criterion, stats in scene["stats"].items():
        _check_stats(criterion, stats)
    claude = scene.get("claude")
    if claude is not None:
        if not isinstance(claude, dict) or set(claude) != set(_CLAUDE_FIELDS) or claude["verdict"] not in VERDICTS:
            raise InvalidInputError(f"{where}: claude must be null or hold {', '.join(_CLAUDE_FIELDS)}")
    elif "claude" not in scene:
        raise InvalidInputError(f"{where}: claude is missing")
    return scene


def _flat(video_id: str, format_id: str, scene: Scene) -> Scene:
    """A copy of `scene` with the ids of its video and format in front, as `get_scene` and `select_scenes` return it."""
    return {"video_id": video_id, "format_id": format_id, **copy.deepcopy(scene)}


class SceneStore:
    """Select and update scenes. Returned scenes are copies: change the file only with the methods here.

    The file is a tree: videos, each with its formats, each with its scenes (a scene is keyed by its
    first frame). Returned scenes are flat dicts that also carry `video_id` and `format_id`.
    """

    def __init__(self, path: Path = DEFAULT_PATH) -> None:
        self.path = Path(path)
        self._lock_path = self.path.with_name(self.path.name + ".lock")
        self._videos: list[dict] | None = None  # loaded state while a transaction is open
        self._depth = 0
        self._dirty = False
        self.timings = {"load": 0.0, "save": 0.0}  # seconds spent reading / writing the file by this store's sessions

    # --- Transactions -----------------------------------------------------------------------------

    @contextlib.contextmanager
    def batch(self) -> Iterator["SceneStore"]:
        """Group operations: one read, one write at the end; nothing is written if the block raises."""
        with self._transaction():
            yield self

    @contextlib.contextmanager
    def _transaction(self) -> Iterator[list[dict]]:
        if self._depth:
            self._depth += 1
            try:
                yield self._videos
            finally:
                self._depth -= 1
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._lock_path, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            started = perf_counter()
            self._videos, self._dirty, self._depth = self._load(), False, 1
            self.timings["load"] += perf_counter() - started
            try:
                yield self._videos
                self._flush()
            finally:
                self._videos, self._depth, self._dirty = None, 0, False

    def _flush(self) -> bool:
        """Write the open session's unsaved changes, if any; True if the file was written."""
        if not self._dirty:
            return False
        started = perf_counter()
        self._save(self._videos)
        self._dirty = False
        self.timings["save"] += perf_counter() - started
        return True

    def save(self) -> Response:
        """Write the open session's changes to the file now, and carry on: 200 written, 204 nothing to write,
        400 outside a session. The session still saves what changes after this when it closes (and rolls back to
        this point, not to the start, if its block raises)."""
        if not self._depth:
            return Response(Status.BAD_REQUEST, "save() needs an open batch()")
        return Response(Status.OK if self._flush() else Status.NO_CONTENT)

    def _load(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            data = yaml.load(self.path.read_text(encoding="utf-8"), Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))
        except (OSError, yaml.YAMLError, UnicodeDecodeError) as exc:
            raise SceneStoreError(f"{self.path} can't be read: {exc}") from exc
        if not isinstance(data, dict) or data.get("version") != VERSION or not isinstance(data.get("videos"), list):
            raise SceneStoreError(f"{self.path} is not a version {VERSION} scene database")
        seen_videos = set()
        for video in data["videos"]:
            if not isinstance(video, dict) or not isinstance(video.get("video_id"), str) \
                    or not isinstance(video.get("formats"), list) or video["video_id"] in seen_videos:
                raise SceneStoreError(f"{self.path}: bad or duplicate video entry {video!r:.80}")
            seen_videos.add(video["video_id"])
            seen_formats = set()
            for fmt in video["formats"]:
                if not isinstance(fmt, dict) or not isinstance(fmt.get("format_id"), str) \
                        or not isinstance(fmt.get("scenes"), list) or fmt["format_id"] in seen_formats:
                    raise SceneStoreError(f"{self.path}: bad or duplicate format entry in {video['video_id']}")
                seen_formats.add(fmt["format_id"])
                last = -1
                for scene in fmt["scenes"]:
                    where = f"{self.path} {video['video_id']}/{fmt['format_id']} scene {scene.get('first_frame') if isinstance(scene, dict) else '?'}"
                    try:
                        _check_scene(scene, where)
                    except InvalidInputError as exc:
                        raise SceneStoreError(str(exc)) from exc
                    if scene["first_frame"] <= last:
                        raise SceneStoreError(f"{where}: scenes must be ascending and not overlap")
                    last = scene["last_frame"]
        return data["videos"]

    def _save(self, videos: list[dict]) -> None:
        text = yaml.safe_dump({"version": VERSION, "videos": videos}, sort_keys=False, default_flow_style=False)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=self.path.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            if self.path.exists():
                shutil.copy2(self.path, self.path.with_name(self.path.name + ".bak"))
            os.replace(tmp, self.path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    @staticmethod
    def _scenes_of(videos: list[dict], video_id: str, format_id: str, create: bool = False) -> list[Scene] | None:
        """The scene list of a video's format; with `create`, the video and format entries are added if absent."""
        video = next((v for v in videos if v["video_id"] == video_id), None)
        if video is None:
            if not create:
                return None
            video = {"video_id": video_id, "formats": []}
            videos.append(video)
        fmt = next((f for f in video["formats"] if f["format_id"] == format_id), None)
        if fmt is None:
            if not create:
                return None
            fmt = {"format_id": format_id, "scenes": []}
            video["formats"].append(fmt)
        return fmt["scenes"]

    @staticmethod
    def _starting_at(scenes: list[Scene] | None, first_frame: int) -> Scene | None:
        return next((s for s in scenes or [] if s["first_frame"] == first_frame), None)

    # --- Operations -------------------------------------------------------------------------------
    # Every operation returns a `Response`; none raises for a bad argument, a missing or duplicate
    # scene, or an unreadable file (only `batch()` raises when the file can't be read, and I/O errors
    # such as a full disk propagate).

    def _guarded(self, work: Callable[[], Response]) -> Response:
        try:
            return work()
        except InvalidInputError as exc:
            return Response(Status.BAD_REQUEST, str(exc))
        except SceneStoreError as exc:
            return Response(Status.SERVER_ERROR, str(exc))

    def insert_scene(self, video_id: str, format_id: str, first_frame: int, last_frame: int, start_ts: float,
                     end_ts: float, frame_count: int, stats: dict[str, dict] | None = None) -> Response:
        """Add the scene `first_frame..last_frame`: 201; 409 if a scene starts at `first_frame` or the new one
        overlaps another (nothing changes); 400 for invalid values."""

        def work() -> Response:
            scene = _check_scene(_plain({
                "first_frame": first_frame, "last_frame": last_frame, "start_ts": start_ts, "end_ts": end_ts,
                "frame_count": frame_count, "claude": None, "stats": stats or {},
            }), "new scene")
            with self._transaction() as videos:
                existing = self._scenes_of(videos, video_id, format_id)
                if self._starting_at(existing, first_frame):
                    return Response(Status.CONFLICT, f"scene {video_id}/{format_id}/frame {first_frame} already exists")
                clash = next((s for s in existing or [] if s["first_frame"] <= last_frame and first_frame <= s["last_frame"]), None)
                if clash:
                    return Response(Status.CONFLICT, f"frames {first_frame}-{last_frame} overlap the scene "
                                                     f"{clash['first_frame']}-{clash['last_frame']}")
                scenes = self._scenes_of(videos, video_id, format_id, create=True)
                scenes.append(scene)
                scenes.sort(key=lambda s: s["first_frame"])
                self._dirty = True
                return Response(Status.CREATED)

        return self._guarded(work)

    def set_criterion_stats(self, video_id: str, format_id: str, first_frame: int, criterion: str,
                            stats: dict) -> Response:
        """Set one criterion's stats on the scene starting at `first_frame`: 201 if the criterion is new on it,
        200 if its stats were replaced, 204 if they were already exactly these; 404 no such scene; 400 invalid."""

        def work() -> Response:
            checked = _check_stats(criterion, stats)
            with self._transaction() as videos:
                scene = self._starting_at(self._scenes_of(videos, video_id, format_id), first_frame)
                if scene is None:
                    return Response(Status.NOT_FOUND, f"no scene {video_id}/{format_id}/frame {first_frame}")
                before = scene["stats"].get(criterion)
                if before == checked:
                    return Response(Status.NO_CONTENT)
                scene["stats"][criterion] = checked
                self._dirty = True
                return Response(Status.CREATED if before is None else Status.OK)

        return self._guarded(work)

    def get_scene(self, video_id: str, format_id: str, first_frame: int) -> Response:
        """200 with the scene that starts at `first_frame` as `data`; 404 if none does."""

        def work() -> Response:
            with self._transaction() as videos:
                scene = self._starting_at(self._scenes_of(videos, video_id, format_id), first_frame)
                if scene is None:
                    return Response(Status.NOT_FOUND, f"no scene {video_id}/{format_id}/frame {first_frame}")
                return Response(Status.OK, data=_flat(video_id, format_id, scene))

        return self._guarded(work)

    def find_scene(self, video_id: str, format_id: str, frame_index: int) -> Response:
        """200 with the scene containing the frame `(video_id, format_id, frame_index)` as `data`; 404 if none."""

        def work() -> Response:
            with self._transaction() as videos:
                scene = self._by_frame(videos, video_id, format_id, frame_index)
                if scene is None:
                    return Response(Status.NOT_FOUND, f"no scene holds frame {frame_index} of {video_id}/{format_id}")
                return Response(Status.OK, data=_flat(video_id, format_id, scene))

        return self._guarded(work)

    def _by_frame(self, videos: list[dict], video_id: str, format_id: str, frame_index: int) -> Scene | None:
        return next((s for s in self._scenes_of(videos, video_id, format_id) or []
                     if s["first_frame"] <= frame_index <= s["last_frame"]), None)

    def select_scenes(self, predicate: Callable[[Scene], bool] = lambda scene: True) -> Response:
        """200 with a list of copies of every scene for which `predicate(scene)` is true, in file order, as `data`."""

        def work() -> Response:
            with self._transaction() as videos:
                flat = (_flat(v["video_id"], f["format_id"], s) for v in videos for f in v["formats"] for s in f["scenes"])
                return Response(Status.OK, data=[s for s in flat if predicate(s)])

        return self._guarded(work)

    def snapshot(self, predicate: Callable[[Scene], bool] = lambda scene: True) -> Response:
        """Like `select_scenes`, but from the last saved file and without the lock, so it never waits for a writer.

        Writes replace the file atomically, so this always sees one complete saved version; the unsaved changes of
        another process's open session are not in it. Inside this store's own session it reads the session's state.
        """

        def work() -> Response:
            videos = self._videos if self._depth else self._load()
            flat = (_flat(v["video_id"], f["format_id"], s) for v in videos for f in v["formats"] for s in f["scenes"])
            return Response(Status.OK, data=[s for s in flat if predicate(s)])

        return self._guarded(work)

    def set_claude_status(self, video_id: str, format_id: str, frame_index: int, verdict: str, reason: str = "",
                          check: str = "miss") -> Response:
        """Record Claude's verdict on the scene holding this frame: 201 if it had none, 200 if it replaced a
        different one, 204 if verdict, reason and check are unchanged (`checked_at` is then kept);
        404 no such scene; 400 invalid."""

        def work() -> Response:
            if verdict not in VERDICTS:
                raise InvalidInputError(f"verdict must be one of {', '.join(VERDICTS)}, not {verdict!r}")
            if check not in CHECKS:
                raise InvalidInputError(f"check must be one of {', '.join(CHECKS)}, not {check!r}")
            with self._transaction() as videos:
                scene = self._by_frame(videos, video_id, format_id, frame_index)
                if scene is None:
                    return Response(Status.NOT_FOUND, f"no scene holds frame {frame_index} of {video_id}/{format_id}")
                before = scene["claude"]
                if before and (before["verdict"], before["reason"], before["check"]) == (verdict, str(reason), check):
                    return Response(Status.NO_CONTENT)
                scene["claude"] = {"verdict": verdict, "reason": str(reason), "check": check,
                                   "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
                self._dirty = True
                return Response(Status.CREATED if before is None else Status.OK)

        return self._guarded(work)
