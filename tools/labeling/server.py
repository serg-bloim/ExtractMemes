"""The labeler's web app: the page, a state endpoint, thumbnails, frames and the marks API.

`LabelerApp` holds the labeling state; `create_flask_app` exposes it over HTTP. Meant to run on
loopback only. Every change to the marks is written to the dataset file straight away.
"""

import threading
from pathlib import Path
from urllib.parse import urlsplit

import cv2
from flask import Flask, Response, jsonify, request

from . import criteria as criteria_module
from . import dataset as dataset_module
from .dataset import Dataset
from .index import FrameReader, Index

PAGE = Path(__file__).with_name("page.html")
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost"}


class LabelerApp:
    """The dataset being labeled, its index and a frame reader; the handler's only collaborator."""

    def __init__(self, dataset: Dataset, dataset_file: Path, index: Index, video_path: Path) -> None:
        self.dataset = dataset
        self.dataset_file = dataset_file
        self.index = index
        self.reader = FrameReader(video_path, index.pts)
        self._lock = threading.Lock()

    def close(self) -> None:
        self.reader.close()

    def state(self) -> dict:
        index, video = self.index, self.dataset.video
        return {
            "video": {"id": video.id, "url": video.url, "format_id": video.format_id,
                      "width": video.width, "height": video.height},
            "fps": index.fps,
            "step": index.step,
            "native_fps": index.native_fps,
            "frame_count": len(index.pts),
            "window": dataset_module.EXCLUSION_WINDOW_SECONDS,
            "rows": index.rows.tolist(),
            "pts": [round(float(t), 3) for t in index.pts],
            "criteria": [{"name": c.name, "threshold": c.threshold} for c in criteria_module.CRITERIA],
            "scores": {name: [round(float(v), 2) for v in values] for name, values in index.scores.items()},
            "verdict": [int(v) for v in index.verdict],
            **self.labels(),
        }

    def labels(self) -> dict:
        return {
            "memes": [{"ts": m.meme_ts, "frame": m.meme_frame} for m in self.dataset.memes],
            "not_memes": [{"ts": n.not_meme_ts, "frame": n.not_meme_frame} for n in self.dataset.not_memes],
        }

    @staticmethod
    def _check_label(label) -> str:
        if label not in ("meme", "not_meme"):
            raise ValueError("label must be 'meme' or 'not_meme'")
        return label

    def _apply(self, frame: int, on: bool, label: str) -> None:
        ts = float(self.index.pts[frame])
        if label == "meme":
            self.dataset.add(frame, ts) if on else self.dataset.remove(frame)
        else:
            self.dataset.add_not_meme(frame, ts) if on else self.dataset.remove_not_meme(frame)

    def _check_frame(self, frame) -> int:
        if not isinstance(frame, int) or isinstance(frame, bool) or not 0 <= frame < len(self.index.pts):
            raise ValueError(f"frame must be an index in 0..{len(self.index.pts) - 1}")
        return frame

    def _save(self) -> None:
        dataset_module.save(self.dataset, self.dataset_file)

    def mark(self, frame, on, label="meme") -> dict:
        frame, label = self._check_frame(frame), self._check_label(label)
        with self._lock:
            self._apply(frame, on, label)
            self._save()
        return self.labels()

    def mark_many(self, frames, on, label="meme") -> dict:
        if not isinstance(frames, list) or not frames:
            raise ValueError("frames must be a non-empty list")
        frames, label = [self._check_frame(f) for f in frames], self._check_label(label)
        with self._lock:
            for frame in frames:
                self._apply(frame, on, label)
            self._save()  # once for the whole batch
        return self.labels()

    def move(self, old, new) -> list[dict]:
        old, new = self._check_frame(old), self._check_frame(new)
        with self._lock:
            self.dataset.remove(old)
            self.dataset.add(new, float(self.index.pts[new]))
            self._save()
        return self.labels()

    def thumb(self, frame: int) -> bytes | None:
        path = self.index.thumb_dir / f"{frame}.jpg"
        return path.read_bytes() if path.is_file() else None

    def frame_jpeg(self, frame: int) -> bytes:
        ok, buffer = cv2.imencode(".jpg", self.reader.get(self._check_frame(frame)),
                                  [cv2.IMWRITE_JPEG_QUALITY, 92])
        if not ok:
            raise RuntimeError(f"Could not encode frame {frame}")
        return buffer.tobytes()


def _host_of(netloc: str | None) -> str | None:
    return urlsplit("//" + netloc).hostname if netloc else None


def create_flask_app(labeler: LabelerApp) -> Flask:
    """The HTTP interface of `labeler`: only the page, its API, thumbnails and frames."""
    web = Flask(__name__)

    @web.before_request
    def only_loopback_hosts():
        # Refuses requests addressed to another name (DNS rebinding) and cross-site posts.
        if _host_of(request.host) not in _LOOPBACK_HOSTS:
            return Response("forbidden", 403, mimetype="text/plain")
        origin = request.headers.get("Origin")
        if origin is not None and _host_of(urlsplit(origin).netloc) not in _LOOPBACK_HOSTS:
            return Response("forbidden", 403, mimetype="text/plain")

    @web.after_request
    def no_store(response):
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    @web.get("/")
    def page():
        return Response(PAGE.read_bytes(), mimetype="text/html")

    @web.get("/api/state")
    def state():
        return jsonify(labeler.state())

    @web.get("/thumb/<int:frame>.jpg")
    def thumb(frame: int):
        body = labeler.thumb(frame)
        if body is None:
            return Response("not found", 404, mimetype="text/plain")
        return Response(body, mimetype="image/jpeg", headers={"Cache-Control": "max-age=3600"})

    @web.get("/frame/<int:frame>.jpg")
    def full_frame(frame: int):
        try:
            body = labeler.frame_jpeg(frame)
        except (ValueError, IndexError):
            return Response("not found", 404, mimetype="text/plain")
        except Exception as exc:  # a decode problem should be visible in the page, not hang it
            return Response(str(exc), 500, mimetype="text/plain")
        return Response(body, mimetype="image/jpeg", headers={"Cache-Control": "max-age=3600"})

    def post_labels(action):
        body = request.get_json(silent=True) or {}
        try:
            return jsonify(action(body))
        except (ValueError, TypeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @web.post("/api/mark")
    def mark():
        return post_labels(lambda b: labeler.mark(b.get("frame"), bool(b.get("on")), b.get("label", "meme")))

    @web.post("/api/mark_many")
    def mark_many():
        return post_labels(
            lambda b: labeler.mark_many(b.get("frames"), bool(b.get("on")), b.get("label", "meme"))
        )

    @web.post("/api/move")
    def move():
        return post_labels(lambda b: labeler.move(b.get("from"), b.get("to")))

    return web
