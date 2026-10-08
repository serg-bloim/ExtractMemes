"""A cache of per-frame facts about one video, built in one sequential pass, and random frame access.

The labeler needs, for the video it labels: every frame's own timestamp, a score per criterion for
every frame, the production classifier's verdict for it, and a grouping of the frames into rows (a row
is a run of consecutive frames that look alike, so a row is a shot or a glitch card) with a thumbnail
for the middle frame of each row (the first and last frames of a shot can be fades). These are cached
under `.runtime/labeler/` (never in the repo). A pass over the video is only made for what is
missing, so adding a criterion computes just that criterion.
"""

import hashlib
import json
import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from tqdm import tqdm

from extract_memes import criteria as criteria_package
from extract_memes.classifier import FrameClassifier
from extract_memes.criteria import Criterion
from extract_memes.heuristic_classifier import HeuristicClassifier
from extract_memes.rule_classifier import RuleClassifier

from . import similarity

CACHE_ROOT = Path(".runtime/labeler")
THUMB_SIZE = (192, 108)
_VERDICT = "__verdict__"
_STEPS = "__steps__"  # how much each frame differs from the one before it (see `similarity`)


@dataclass
class Index:
    """Everything the page needs about the frames and their rows."""

    pts: np.ndarray  # timestamp (seconds) of every decoded frame, by frame index
    rows: np.ndarray  # first frame of each row, ascending; a row runs to the frame before the next row
    row_last: np.ndarray  # last frame of each row
    criteria: list[Criterion]  # every criterion in extract_memes.criteria, as scored
    scores: dict[str, np.ndarray]  # criterion name -> score per frame
    thresholds: dict[str, list[dict]]  # criterion name -> the classifier's conditions on it [{op, value}]
    verdict: np.ndarray  # the production classifier's decision per frame
    native_fps: float
    thumb_dir: Path
    version: str = ""  # identifies this video file, so cached images can't be mixed up


def _read_meta(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def write_thumb(path: Path, frame: np.ndarray) -> None:
    small = cv2.resize(frame, THUMB_SIZE, interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(path), small, [cv2.IMWRITE_JPEG_QUALITY, 70])


def row_bounds(steps: np.ndarray, threshold: float = similarity.CUT_THRESHOLD) -> tuple[np.ndarray, np.ndarray]:
    """`(first, last)` frame of each row: a new row starts where a frame differs from the one before it by more than `threshold`."""
    first = np.flatnonzero(np.concatenate([[True], steps[1:] > threshold]))
    return first, np.append(first[1:] - 1, len(steps) - 1)


def build(
    video_path: Path,
    cache_dir: Path,
    criteria: list[Criterion] | None = None,
    progress: Callable[[str, float | None], None] | None = None,
    classifier: FrameClassifier | None = None,
) -> Index:
    """Load the cached index for `video_path`, running a pass over the video for what's missing.

    Scores come from the criteria in `extract_memes.criteria` (all of them unless `criteria` is
    given) and the verdict from `classifier` (default: the pipeline's `HeuristicClassifier()`), so
    they are the same numbers the pipeline computes. Each is cached with a fingerprint of its code.
    """
    criteria = list(criteria_package.all_criteria().values()) if criteria is None else criteria
    classifier = HeuristicClassifier() if classifier is None else classifier
    cache_dir.mkdir(parents=True, exist_ok=True)
    thumb_dir = cache_dir / "thumbs"
    thumb_dir.mkdir(exist_ok=True)
    stat = video_path.stat()
    identity = {"size": stat.st_size, "mtime": int(stat.st_mtime), "every_frame": True, "rows": "similar-frames"}
    meta_path = cache_dir / "meta.json"
    meta = _read_meta(meta_path)
    if {k: meta.get(k) for k in identity} != identity:
        for stale in cache_dir.glob("*.npy"):
            stale.unlink()
        for stale in thumb_dir.glob("*.jpg"):
            stale.unlink()
        meta = dict(identity)
    hashes: dict[str, str] = meta.setdefault("hashes", {})

    wanted = {c.name: c.fingerprint() for c in criteria}
    wanted[_VERDICT] = _classifier_fingerprint(classifier)
    wanted[_STEPS] = hashlib.sha1(Path(similarity.__file__).read_bytes()).hexdigest()[:12]
    stale_scores = {name for name, h in wanted.items() if hashes.get(name) != h
                    or not (cache_dir / (f"{name}.npy" if name != _STEPS else "steps.npy")).is_file()}
    pts_path = cache_dir / "pts.npy"
    need_pts = not pts_path.is_file()
    steps_path = cache_dir / "steps.npy"

    if need_pts or stale_scores:
        _run_pass(video_path, cache_dir, criteria, stale_scores, need_pts, progress, classifier)
        hashes[_STEPS] = wanted[_STEPS]
        for name in stale_scores:
            hashes[name] = wanted[name]
        meta_path.write_text(json.dumps(meta))

    pts = np.load(pts_path)
    rows, row_last = row_bounds(np.load(steps_path))
    middle = (rows + row_last) // 2
    missing = {int(f) for f in middle if not (thumb_dir / f"{f}.jpg").is_file()}
    if missing:
        _write_thumbs(video_path, missing, thumb_dir, progress)
    cap = cv2.VideoCapture(str(video_path))
    native_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    cap.release()
    return Index(
        pts=pts,
        rows=rows,
        row_last=row_last,
        criteria=criteria,
        scores={c.name: np.load(cache_dir / f"{c.name}.npy") for c in criteria},
        thresholds=_thresholds(classifier),
        verdict=np.load(cache_dir / f"{_VERDICT}.npy"),
        native_fps=native_fps,
        thumb_dir=thumb_dir,
        version=f"{identity['size']}-{identity['mtime']}-rows",
    )


def _classifier_fingerprint(classifier: FrameClassifier) -> str:
    if isinstance(classifier, RuleClassifier):
        return classifier.fingerprint()
    import hashlib
    import inspect

    return hashlib.sha1(inspect.getsource(type(classifier)).encode()).hexdigest()[:12]


def _thresholds(classifier: FrameClassifier) -> dict[str, list[dict]]:
    """What a rule classifier compares each criterion with, so the page can draw it."""
    found: dict[str, list[dict]] = {}
    if isinstance(classifier, RuleClassifier):
        for condition in classifier.rule.conditions():
            found.setdefault(condition.criterion, []).append({"op": condition.op, "value": condition.value})
    return found


def _write_thumbs(video_path: Path, wanted: set[int], thumb_dir: Path, progress=None) -> None:
    """Write the thumbnails of the `wanted` frames in one sequential decode."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video file: {video_path}")
    last = max(wanted)
    try:
        for index in range(last + 1):
            if not cap.grab():
                break
            if index in wanted:
                ok, frame = cap.retrieve()
                if ok:
                    write_thumb(thumb_dir / f"{index}.jpg", frame)
            if progress and index % 2000 == 0:
                progress("Making thumbnails", min(1.0, index / (last + 1)))
    finally:
        cap.release()


def _run_pass(video_path, cache_dir, criteria, stale, need_pts, progress=None,
              classifier=None) -> None:
    """One sequential decode that fills in whatever is missing."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video file: {video_path}")
    todo = [c for c in criteria if c.name in stale]
    do_verdict = _VERDICT in stale
    pts: list[float] = []
    steps: list[float] = []
    previous = None
    scores: dict[str, list[float]] = {c.name: [] for c in todo}
    verdicts: list[bool] = []
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or None
    try:
        with tqdm(total=total, desc="Indexing video", unit="frame") as bar:
            index = 0
            while cap.grab():
                if need_pts:
                    pts.append(cap.get(cv2.CAP_PROP_POS_MSEC) / 1000)
                ok, frame = cap.retrieve()
                if ok:
                    current = similarity.descriptor(frame)
                    steps.append(np.inf if previous is None else similarity.step(previous, current))
                    previous = current
                    for criterion in todo:
                        scores[criterion.name].append(criterion.score(frame))
                    if do_verdict:
                        verdicts.append(classifier.is_meme_frame(frame))
                index += 1
                bar.update(1)
                if progress and total and index % 500 == 0:
                    progress("Indexing video", min(1.0, index / total))
    finally:
        cap.release()
    np.save(cache_dir / "steps.npy", np.array(steps, dtype=np.float32))
    if need_pts:
        np.save(cache_dir / "pts.npy", np.array(pts))
    for name, values in scores.items():
        np.save(cache_dir / f"{name}.npy", np.array(values, dtype=np.float32))
    if do_verdict:
        np.save(cache_dir / f"{_VERDICT}.npy", np.array(verdicts, dtype=bool))


class FrameReader:
    """Full-size frames by index. Seeking only gets near a frame, so a frame is found by reading
    forward and checking each frame's own timestamp against the index's `pts`."""

    _CACHE = 300
    _FORWARD = 200  # read forward instead of seeking when the target is this close ahead

    def __init__(self, video_path: Path, pts: np.ndarray) -> None:
        self._path = video_path
        self._cap = cv2.VideoCapture(str(video_path))
        if not self._cap.isOpened():
            raise RuntimeError(f"Could not open video file: {video_path}")
        self._pts = pts
        self._pos: int | None = None  # index of the frame the next read returns, when known
        self._cache: OrderedDict[int, np.ndarray] = OrderedDict()
        self._lock = threading.Lock()

    def close(self) -> None:
        self._cap.release()

    def _remember(self, index: int, frame: np.ndarray) -> None:
        self._cache[index] = frame
        self._cache.move_to_end(index)
        while len(self._cache) > self._CACHE:
            self._cache.popitem(last=False)

    def _index_of_last_read(self) -> int:
        ts = self._cap.get(cv2.CAP_PROP_POS_MSEC) / 1000
        found = int(np.searchsorted(self._pts, ts - 0.0005))
        if found >= len(self._pts) or abs(self._pts[found] - ts) > 0.0005:
            raise RuntimeError(f"A frame at {ts:.3f}s has no matching index")
        return found

    def _reopen(self) -> None:
        """Start decoding from the first frame again. Some streams (H.264 with B-frames) can't be
        seeked to their first frames: a seek to 0 lands on the first frame the decoder can restart
        from, which can be over a hundred frames in."""
        self._cap.release()
        self._cap = cv2.VideoCapture(str(self._path))
        if not self._cap.isOpened():
            raise RuntimeError(f"Could not open video file: {self._path}")
        self._pos = 0

    def _seek(self, start: int) -> int:
        """Land near `start`; return the index of the frame that was read there."""
        self._cap.set(cv2.CAP_PROP_POS_FRAMES, start)
        ok, frame = self._cap.read()
        if not ok:
            raise RuntimeError(f"Could not read near frame {start}")
        landed = self._index_of_last_read()
        self._remember(landed, frame)
        self._pos = landed + 1
        return landed

    def get(self, index: int) -> np.ndarray:
        if not 0 <= index < len(self._pts):
            raise IndexError(index)
        with self._lock:
            if index in self._cache:
                self._cache.move_to_end(index)
                return self._cache[index]
            start = max(0, index - 30)
            while self._pos is None or not (0 <= index - self._pos <= self._FORWARD):
                landed = self._seek(start)
                if landed <= index:
                    break
                if start == 0:
                    self._reopen()      # seeking can't get this early; decode from the beginning
                    break
                start = max(0, start - 100)
            while self._pos <= index:
                ok, frame = self._cap.read()
                if not ok:
                    raise RuntimeError(f"Could not read frame {self._pos}")
                self._remember(self._pos, frame)
                self._pos += 1
            return self._cache[index]
