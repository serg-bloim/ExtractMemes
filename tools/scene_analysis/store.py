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
from datetime import datetime, timezone
from pathlib import Path

import yaml

DEFAULT_PATH = Path("data/datasets/scene_analysis/scene_analysis.yaml")
VERSION = 1
VERDICTS = ("meme", "not_meme", "unsure")
CHECKS = ("miss", "false_positive")

_SCENE_FIELDS = {"video_id": str, "format_id": str, "scene_index": int, "first_frame": int, "last_frame": int,
                 "start_ts": (int, float), "end_ts": (int, float), "frame_count": int}
_STATS_FIELDS = ("op", "threshold", "min", "max", "mean", "std", "share_flagged")
_NUMERIC_STATS = _STATS_FIELDS[1:]
_CLAUDE_FIELDS = ("verdict", "reason", "check", "checked_at")

Scene = dict


class SceneStoreError(RuntimeError):
    """The file is unreadable or does not match the schema, or an argument is invalid."""


class SceneExistsError(SceneStoreError):
    """A scene with this (video_id, format_id, scene_index) is already stored."""


class SceneNotFoundError(SceneStoreError):
    """No stored scene matches the key or frame locator."""


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
    stats = _plain(stats)
    if set(stats) != set(_STATS_FIELDS):
        raise SceneStoreError(f"stats of {criterion!r} must have exactly {', '.join(_STATS_FIELDS)}; got {sorted(stats)}")
    if not isinstance(stats["op"], str):
        raise SceneStoreError(f"stats of {criterion!r}: op must be a string")
    for name in _NUMERIC_STATS:
        if isinstance(stats[name], bool) or not isinstance(stats[name], (int, float)):
            raise SceneStoreError(f"stats of {criterion!r}: {name} must be a number, not {stats[name]!r}")
    return stats


def _check_scene(scene: object, where: str = "scene") -> Scene:
    if not isinstance(scene, dict):
        raise SceneStoreError(f"{where} is not a mapping")
    for name, kind in _SCENE_FIELDS.items():
        value = scene.get(name)
        if isinstance(value, bool) or not isinstance(value, kind):
            raise SceneStoreError(f"{where}: {name} is missing or invalid ({value!r})")
    if not isinstance(scene.get("stats"), dict):
        raise SceneStoreError(f"{where}: stats must be a mapping")
    for criterion, stats in scene["stats"].items():
        _check_stats(criterion, stats)
    claude = scene.get("claude")
    if claude is not None:
        if not isinstance(claude, dict) or set(claude) != set(_CLAUDE_FIELDS) or claude["verdict"] not in VERDICTS:
            raise SceneStoreError(f"{where}: claude must be null or hold {', '.join(_CLAUDE_FIELDS)}")
    elif "claude" not in scene:
        raise SceneStoreError(f"{where}: claude is missing")
    return scene


def _key(scene: Scene) -> tuple[str, str, int]:
    return scene["video_id"], scene["format_id"], scene["scene_index"]


class SceneStore:
    """Select and update scenes. Returned scenes are copies: change the file only with the methods here."""

    def __init__(self, path: Path = DEFAULT_PATH) -> None:
        self.path = Path(path)
        self._lock_path = self.path.with_name(self.path.name + ".lock")
        self._scenes: list[Scene] | None = None  # loaded state while a transaction is open
        self._depth = 0
        self._dirty = False

    # --- Transactions -----------------------------------------------------------------------------

    @contextlib.contextmanager
    def batch(self) -> Iterator["SceneStore"]:
        """Group operations: one read, one write at the end; nothing is written if the block raises."""
        with self._transaction():
            yield self

    @contextlib.contextmanager
    def _transaction(self) -> Iterator[list[Scene]]:
        if self._depth:
            self._depth += 1
            try:
                yield self._scenes
            finally:
                self._depth -= 1
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._lock_path, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self._scenes, self._dirty, self._depth = self._load(), False, 1
            try:
                yield self._scenes
                if self._dirty:
                    self._save(self._scenes)
            finally:
                self._scenes, self._depth, self._dirty = None, 0, False

    def _load(self) -> list[Scene]:
        if not self.path.exists():
            return []
        try:
            data = yaml.load(self.path.read_text(encoding="utf-8"), Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))
        except (OSError, yaml.YAMLError, UnicodeDecodeError) as exc:
            raise SceneStoreError(f"{self.path} can't be read: {exc}") from exc
        if not isinstance(data, dict) or data.get("version") != VERSION or not isinstance(data.get("scenes"), list):
            raise SceneStoreError(f"{self.path} is not a version {VERSION} scene database")
        seen = set()
        for i, scene in enumerate(data["scenes"]):
            _check_scene(scene, f"{self.path} scene #{i}")
            if _key(scene) in seen:
                raise SceneStoreError(f"{self.path}: duplicate scene {_key(scene)}")
            seen.add(_key(scene))
        return data["scenes"]

    def _save(self, scenes: list[Scene]) -> None:
        text = yaml.safe_dump({"version": VERSION, "scenes": scenes}, sort_keys=False, default_flow_style=False)
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

    def _find(self, scenes: list[Scene], video_id: str, format_id: str, scene_index: int) -> Scene | None:
        return next((s for s in scenes if _key(s) == (video_id, format_id, scene_index)), None)

    # --- Operations -------------------------------------------------------------------------------

    def insert_scene(self, video_id: str, format_id: str, scene_index: int, first_frame: int, last_frame: int,
                     start_ts: float, end_ts: float, frame_count: int, stats: dict[str, dict] | None = None) -> None:
        """Add a scene; raises `SceneExistsError` if its key is taken (nothing changes)."""
        scene = _check_scene(_plain({
            "video_id": video_id, "format_id": format_id, "scene_index": scene_index, "first_frame": first_frame,
            "last_frame": last_frame, "start_ts": start_ts, "end_ts": end_ts, "frame_count": frame_count,
            "stats": stats or {}, "claude": None,
        }), "new scene")
        if scene["first_frame"] > scene["last_frame"]:
            raise SceneStoreError("first_frame is after last_frame")
        with self._transaction() as scenes:
            if self._find(scenes, video_id, format_id, scene_index):
                raise SceneExistsError(f"scene {video_id}/{format_id}/{scene_index} already exists")
            scenes.append(scene)
            self._dirty = True

    def set_criterion_stats(self, video_id: str, format_id: str, scene_index: int, criterion: str, stats: dict) -> None:
        """Add or replace one criterion's stats on a scene; raises `SceneNotFoundError`."""
        stats = _check_stats(criterion, stats)
        with self._transaction() as scenes:
            scene = self._find(scenes, video_id, format_id, scene_index)
            if scene is None:
                raise SceneNotFoundError(f"no scene {video_id}/{format_id}/{scene_index}")
            scene["stats"][criterion] = stats
            self._dirty = True

    def get_scene(self, video_id: str, format_id: str, scene_index: int) -> Scene:
        with self._transaction() as scenes:
            scene = self._find(scenes, video_id, format_id, scene_index)
            if scene is None:
                raise SceneNotFoundError(f"no scene {video_id}/{format_id}/{scene_index}")
            return copy.deepcopy(scene)

    def find_scene(self, video_id: str, format_id: str, frame_index: int) -> Scene:
        """The scene containing the frame `(video_id, format_id, frame_index)`."""
        with self._transaction() as scenes:
            return copy.deepcopy(self._by_frame(scenes, video_id, format_id, frame_index))

    def _by_frame(self, scenes: list[Scene], video_id: str, format_id: str, frame_index: int) -> Scene:
        for scene in scenes:
            if scene["video_id"] == video_id and scene["format_id"] == format_id \
                    and scene["first_frame"] <= frame_index <= scene["last_frame"]:
                return scene
        raise SceneNotFoundError(f"no scene holds frame {frame_index} of {video_id}/{format_id}")

    def select_scenes(self, predicate: Callable[[Scene], bool] = lambda scene: True) -> list[Scene]:
        """Copies of every scene for which `predicate(scene)` is true, in file order."""
        with self._transaction() as scenes:
            return [copy.deepcopy(s) for s in scenes if predicate(s)]

    def set_claude_status(self, video_id: str, format_id: str, frame_index: int, verdict: str, reason: str = "",
                          check: str = "miss") -> None:
        """Record Claude's verdict on the scene holding this frame, replacing an earlier one."""
        if verdict not in VERDICTS:
            raise SceneStoreError(f"verdict must be one of {', '.join(VERDICTS)}, not {verdict!r}")
        if check not in CHECKS:
            raise SceneStoreError(f"check must be one of {', '.join(CHECKS)}, not {check!r}")
        with self._transaction() as scenes:
            scene = self._by_frame(scenes, video_id, format_id, frame_index)
            scene["claude"] = {"verdict": verdict, "reason": str(reason), "check": check,
                               "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            self._dirty = True
