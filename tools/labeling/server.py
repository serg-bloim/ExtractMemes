"""The labeler's local web server: the page, a state endpoint, thumbnails, frames and the marks API.

Bound to loopback only. Every change to the marks is written to the dataset file straight away.
"""

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2

from . import criteria as criteria_module
from . import dataset as dataset_module
from .dataset import Dataset
from .index import FrameReader, Index

PAGE = Path(__file__).with_name("page.html")
_THUMB = re.compile(r"^/thumb/(\d+)\.jpg$")
_FRAME = re.compile(r"^/frame/(\d+)\.jpg$")


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
            "memes": self.memes(),
        }

    def memes(self) -> list[dict]:
        return [{"ts": m.meme_ts, "frame": m.meme_frame} for m in self.dataset.memes]

    def _check_frame(self, frame) -> int:
        if not isinstance(frame, int) or isinstance(frame, bool) or not 0 <= frame < len(self.index.pts):
            raise ValueError(f"frame must be an index in 0..{len(self.index.pts) - 1}")
        return frame

    def _save(self) -> None:
        dataset_module.save(self.dataset, self.dataset_file)

    def mark(self, frame, on) -> list[dict]:
        frame = self._check_frame(frame)
        with self._lock:
            if on:
                self.dataset.add(frame, float(self.index.pts[frame]))
            else:
                self.dataset.remove(frame)
            self._save()
        return self.memes()

    def move(self, old, new) -> list[dict]:
        old, new = self._check_frame(old), self._check_frame(new)
        with self._lock:
            self.dataset.remove(old)
            self.dataset.add(new, float(self.index.pts[new]))
            self._save()
        return self.memes()

    def thumb(self, frame: int) -> bytes | None:
        path = self.index.thumb_dir / f"{frame}.jpg"
        return path.read_bytes() if path.is_file() else None

    def frame_jpeg(self, frame: int) -> bytes:
        ok, buffer = cv2.imencode(".jpg", self.reader.get(self._check_frame(frame)),
                                  [cv2.IMWRITE_JPEG_QUALITY, 92])
        if not ok:
            raise RuntimeError(f"Could not encode frame {frame}")
        return buffer.tobytes()


def make_handler(app: LabelerApp, port_getter) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args) -> None:  # keep the terminal for progress and errors
            pass

        def _host_ok(self) -> bool:
            # Refuses requests addressed to another name (DNS rebinding) and cross-site posts.
            port = port_getter()
            allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
            origin = self.headers.get("Origin")
            return self.headers.get("Host") in allowed and (
                origin is None or origin in {f"http://{h}" for h in allowed}
            )

        def _send(self, status: int, body: bytes, content_type: str, cache: str = "no-store") -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload, status: int = 200) -> None:
            self._send(status, json.dumps(payload).encode(), "application/json")

        def _not_found(self) -> None:
            self._send(404, b"not found", "text/plain")

        def do_GET(self) -> None:
            if not self._host_ok():
                return self._send(403, b"forbidden", "text/plain")
            path = self.path.split("?", 1)[0]
            try:
                if path == "/":
                    return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
                if path == "/api/state":
                    return self._json(app.state())
                if match := _THUMB.match(path):
                    body = app.thumb(int(match.group(1)))
                    if body is None:
                        return self._not_found()
                    return self._send(200, body, "image/jpeg", cache="max-age=3600")
                if match := _FRAME.match(path):
                    return self._send(200, app.frame_jpeg(int(match.group(1))), "image/jpeg",
                                      cache="max-age=3600")
            except (ValueError, IndexError):
                return self._not_found()
            except Exception as exc:  # a decode problem should be visible in the page, not hang it
                return self._send(500, str(exc).encode(), "text/plain")
            self._not_found()

        def do_POST(self) -> None:
            if not self._host_ok():
                return self._send(403, b"forbidden", "text/plain")
            if self.path not in ("/api/mark", "/api/move"):
                return self._not_found()
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                if self.path == "/api/mark":
                    memes = app.mark(body.get("frame"), bool(body.get("on")))
                else:
                    memes = app.move(body.get("from"), body.get("to"))
            except (ValueError, TypeError) as exc:
                return self._json({"error": str(exc)}, 400)
            self._json({"memes": memes})

    return Handler


def serve(app: LabelerApp, port: int = 8765) -> ThreadingHTTPServer:
    """Create the loopback server (not yet running); `port=0` picks a free port."""
    holder: dict = {}
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app, lambda: holder["port"]))
    holder["port"] = server.server_address[1]
    return server
