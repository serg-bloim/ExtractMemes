"""A read-only web browser for the scene database: sort, filter and look at scenes (not frames).

Scenes are read through `SceneStore.snapshot`, so browsing never waits for (or disturbs) a `verify` session.
A scene's picture is its middle frame from the labeler's thumbnail cache; if it isn't cached the page shows a
placeholder, because nothing here decodes video.
"""

import threading
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, Response, jsonify, request

from tools.labeling.index import CACHE_ROOT
from tools.labeling.server import _host_of, _local_host

from .store import DEFAULT_PATH, Scene, SceneStore

PAGE = Path(__file__).with_name("browser.html")
PAGE_SIZES = (25, 50, 100, 200)
STAT_KEYS = ("min", "max", "mean", "std", "share_flagged", "distance")
SCENE_KEYS = ("video_id", "first_frame", "start_ts", "frame_count", "verdict", "checked_at")
SORT_KEYS = SCENE_KEYS + STAT_KEYS
_SAFE = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"


def _distance(stats: dict) -> float | None:
    """0 if the scene's scores straddle the threshold, else the gap from its nearest score; None without a threshold."""
    threshold = stats.get("threshold")
    if threshold is None:
        return None
    if stats["min"] <= threshold <= stats["max"]:
        return 0.0
    return min(abs(stats["min"] - threshold), abs(stats["max"] - threshold))


def _view(scene: Scene, criterion: str) -> dict:
    """A scene as the table shows it: its own fields plus the chosen criterion's stats and its distance."""
    stats = scene["stats"].get(criterion)
    shown = None if stats is None else {**stats, "distance": _distance(stats)}
    return {"video_id": scene["video_id"], "format_id": scene["format_id"], "first_frame": scene["first_frame"],
            "last_frame": scene["last_frame"], "start_ts": scene["start_ts"], "end_ts": scene["end_ts"],
            "frame_count": scene["frame_count"], "claude": scene["claude"], "stats": shown}


def _sort_value(view: dict, key: str):
    if key in STAT_KEYS:
        return None if view["stats"] is None else view["stats"][key]
    if key == "verdict":
        return view["claude"] and view["claude"]["verdict"]
    if key == "checked_at":
        return view["claude"] and view["claude"]["checked_at"]
    return view[key]


def _flagged_matches(stats: dict | None, wanted: str) -> bool:
    if wanted == "any":
        return True
    share = None if stats is None else stats["share_flagged"]
    if share is None:
        return False
    return {"none": share == 0, "mixed": 0 < share < 1, "all": share == 1}.get(wanted, True)


def query(scenes: list[Scene], params: dict) -> dict:
    """Filter, sort and page `scenes` by the request parameters (all optional, see `browser.html` for the names)."""
    criteria = sorted({name for s in scenes for name in s["stats"]})
    criterion = params.get("criterion") or ("edge_histogram" if "edge_histogram" in criteria else (criteria[0] if criteria else ""))
    video, fmt = params.get("video") or "", params.get("format") or ""
    claude, check = params.get("claude") or "any", params.get("check") or "any"
    flagged, text = params.get("flagged") or "any", (params.get("q") or "").strip().lower()

    def keep(scene: Scene) -> bool:
        if video and scene["video_id"] != video or fmt and scene["format_id"] != fmt:
            return False
        verdict = scene["claude"]
        if claude == "none" and verdict or claude == "checked" and not verdict:
            return False
        if claude in ("meme", "not_meme", "unsure") and (not verdict or verdict["verdict"] != claude):
            return False
        if check in ("miss", "false_positive") and (not verdict or verdict["check"] != check):
            return False
        if text and not (verdict and text in verdict["reason"].lower()):
            return False
        return _flagged_matches(scene["stats"].get(criterion), flagged)

    views = [_view(s, criterion) for s in scenes if keep(s)]
    key = params.get("sort") if params.get("sort") in SORT_KEYS else "video_id"
    descending = params.get("dir") == "desc"
    present = [v for v in views if _sort_value(v, key) is not None]
    missing = [v for v in views if _sort_value(v, key) is None]  # always last, whichever the direction
    present.sort(key=lambda v: (v["video_id"], v["format_id"], v["first_frame"]))  # stable tie-break
    present.sort(key=lambda v: _sort_value(v, key), reverse=descending)
    views = present + missing

    try:
        size = int(params.get("size", 50))
        page = int(params.get("page", 1))
    except ValueError:
        size, page = 50, 1
    size = size if size in PAGE_SIZES else 50
    pages = max(1, -(-len(views) // size))
    page = min(max(page, 1), pages)
    summary = {"checked": sum(1 for v in views if v["claude"])}
    for name in ("meme", "not_meme", "unsure"):
        summary[name] = sum(1 for v in views if v["claude"] and v["claude"]["verdict"] == name)
    formats: dict[str, set[str]] = {}
    for s in scenes:
        formats.setdefault(s["video_id"], set()).add(s["format_id"])
    return {"total": len(views), "page": page, "pages": pages, "size": size, "criterion": criterion,
            "criteria": criteria, "summary": summary,
            "videos": [{"video_id": v, "formats": sorted(f)} for v, f in sorted(formats.items())],
            "rows": views[(page - 1) * size:page * size]}


class SceneCache:
    """The saved scenes, reloaded only when the database file changes."""

    def __init__(self, store: SceneStore) -> None:
        self.store = store
        self._lock = threading.Lock()
        self._signature: tuple | None = None
        self._scenes: list[Scene] = []

    def get(self) -> list[Scene]:
        path = self.store.path
        try:
            stat = path.stat()
            signature = (stat.st_mtime_ns, stat.st_size)
        except FileNotFoundError:
            signature = None
        with self._lock:
            if signature != self._signature or signature is None:
                response = self.store.snapshot()
                if not response.ok:
                    raise RuntimeError(response.message)
                self._scenes, self._signature = response.data, signature
            return self._scenes


def thumb_path(cache_root: Path, video_id: str, format_id: str, first: int, last: int) -> Path | None:
    """The cached thumbnail of the scene's middle frame (the labeler's thumbnail of a row), if it exists."""
    if not video_id or not format_id or set(video_id + format_id) - set(_SAFE):
        return None
    path = cache_root / f"{video_id}_{format_id}" / "thumbs" / f"{(first + last) // 2}.jpg"
    return path if path.is_file() else None


def create_app(store: SceneStore | None = None, cache_root: Path = CACHE_ROOT) -> Flask:
    store = store or SceneStore(DEFAULT_PATH)
    cache = SceneCache(store)
    web = Flask(__name__)

    @web.before_request
    def only_local_hosts():
        # Refuses requests addressed to another name (DNS rebinding), as the labeler does.
        if not _local_host(_host_of(request.host)):
            return Response("forbidden", 403, mimetype="text/plain")
        origin = request.headers.get("Origin")
        if origin is not None and not _local_host(_host_of(urlsplit(origin).netloc)):
            return Response("forbidden", 403, mimetype="text/plain")

    @web.after_request
    def no_store(response):
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    @web.get("/")
    def page():
        return Response(PAGE.read_bytes(), mimetype="text/html")

    @web.get("/api/scenes")
    def scenes():
        try:
            result = query(cache.get(), request.args.to_dict())
        except RuntimeError as exc:
            return jsonify({"error": str(exc)}), 500
        for row in result["rows"]:
            row["has_thumb"] = thumb_path(cache_root, row["video_id"], row["format_id"], row["first_frame"], row["last_frame"]) is not None
        return jsonify(result)

    @web.get("/api/scene")
    def scene():
        try:
            found = next((s for s in cache.get() if s["video_id"] == request.args.get("video")
                          and s["format_id"] == request.args.get("format")
                          and s["first_frame"] == request.args.get("first", type=int)), None)
        except RuntimeError as exc:
            return jsonify({"error": str(exc)}), 500
        if found is None:
            return jsonify({"error": "no such scene"}), 404
        return jsonify({**found, "has_thumb": thumb_path(cache_root, found["video_id"], found["format_id"],
                                                         found["first_frame"], found["last_frame"]) is not None})

    @web.get("/thumb/<video_id>/<format_id>/<int:first>/<int:last>.jpg")
    def thumb(video_id: str, format_id: str, first: int, last: int):
        path = thumb_path(cache_root, video_id, format_id, first, last)
        if path is None:
            return Response("not cached", 404, mimetype="text/plain")
        return Response(path.read_bytes(), mimetype="image/jpeg", headers={"Cache-Control": "max-age=3600"})

    return web
