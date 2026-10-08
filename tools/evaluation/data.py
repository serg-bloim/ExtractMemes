"""Load the labeled datasets with their cached criterion scores, pooled into one sample set."""

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from extract_memes import criteria as criteria_package
from tools.labeling import dataset as ds
from tools.labeling.index import CACHE_ROOT, build

from .truth import IGNORED, POSITIVE, ground_truth

SCAN_FPS = 3.0


@dataclass
class Samples:
    """Scanned frames of one or more videos: a score per criterion and a label per frame."""

    scores: dict[str, np.ndarray]
    labels: np.ndarray  # truth.POSITIVE / NEGATIVE / IGNORED
    window: np.ndarray  # meme number of a positive frame (unique across videos), -1 otherwise
    video: np.ndarray  # video id of each frame
    frame: np.ndarray  # frame index within its video
    ts: np.ndarray  # timestamp in seconds

    def select(self, mask: np.ndarray) -> "Samples":
        return Samples({n: v[mask] for n, v in self.scores.items()}, self.labels[mask], self.window[mask],
                       self.video[mask], self.frame[mask], self.ts[mask])

    def as_frames(self) -> "Samples":
        """The same frames judged one by one: every positive frame is a meme of its own."""
        window = np.where(self.labels == POSITIVE, np.arange(len(self.labels)), -1).astype(np.int32)
        return Samples(self.scores, self.labels, window, self.video, self.frame, self.ts)

    def labeled(self) -> "Samples":
        return self.select(self.labels != IGNORED)


def _fresh(cache_dir: Path, names: list[str]) -> bool:
    """Whether the cache holds a current score for every criterion in `names`."""
    try:
        meta = json.loads((cache_dir / "meta.json").read_text())
    except (OSError, ValueError):
        return False
    criteria = criteria_package.all_criteria()
    return (cache_dir / "pts.npy").is_file() and all(
        meta.get("hashes", {}).get(n) == criteria[n].fingerprint() and (cache_dir / f"{n}.npy").is_file()
        for n in names
    )


def load_truth(dataset: ds.Dataset, proxy: str | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """`(frame indices, labels, windows)` of the scanned frames, without scoring any criterion.

    Needs only the timestamps of the video's frames, so it works before a criterion's reference
    data exists (which is what building that data requires).
    """
    cache_dir = CACHE_ROOT / f"{dataset.video.id}_{dataset.video.format_id}"
    if not (cache_dir / "pts.npy").is_file() or not (cache_dir / "meta.json").is_file():
        build(ds.ensure_video(dataset, proxy=proxy), cache_dir, fps=SCAN_FPS, criteria=[])
    pts = np.load(cache_dir / "pts.npy")
    step = json.loads((cache_dir / "meta.json").read_text())["step"]
    rows = np.arange(0, len(pts), step)
    labels, windows = ground_truth(dataset, rows, pts)
    return rows, labels, windows


def load_video(dataset: ds.Dataset, refresh: bool = True, proxy: str | None = None) -> Samples:
    """One video's samples, from the labeler cache (rebuilt when stale, unless `refresh` is False)."""
    criteria = criteria_package.all_criteria()
    cache_dir = CACHE_ROOT / f"{dataset.video.id}_{dataset.video.format_id}"
    if not _fresh(cache_dir, list(criteria)):
        if not refresh:
            raise RuntimeError(f"The score cache of {dataset.video.id} is missing or stale: {cache_dir}")
        video_path = ds.ensure_video(dataset, proxy=proxy)
        build(video_path, cache_dir, fps=SCAN_FPS)
    pts = np.load(cache_dir / "pts.npy")
    step = json.loads((cache_dir / "meta.json").read_text())["step"]
    rows = np.arange(0, len(pts), step)
    labels, windows = ground_truth(dataset, rows, pts)
    return Samples(
        scores={n: np.load(cache_dir / f"{n}.npy").astype(float) for n in criteria},
        labels=labels,
        window=windows,
        video=np.full(len(rows), dataset.video.id),
        frame=rows,
        ts=pts[rows],
    )


def pool(parts: list[Samples]) -> Samples:
    offsets = np.cumsum([0] + [int(p.window.max()) + 1 if (p.window >= 0).any() else 0 for p in parts])
    return Samples(
        {n: np.concatenate([p.scores[n] for p in parts]) for n in parts[0].scores},
        np.concatenate([p.labels for p in parts]),
        np.concatenate([np.where(p.window >= 0, p.window + offsets[i], -1) for i, p in enumerate(parts)]),
        np.concatenate([p.video for p in parts]),
        np.concatenate([p.frame for p in parts]),
        np.concatenate([p.ts for p in parts]),
    )


def load_all(video_ids: list[str] | None = None, refresh: bool = True, proxy: str | None = None) -> Samples:
    """Every dataset in `data/datasets/` (or just `video_ids`), pooled."""
    entries = [d["id"] for d in ds.list_datasets()]
    paths = [ds.dataset_path(i) for i in (video_ids or entries)]
    if not paths:
        raise RuntimeError("No datasets found")
    return pool([load_video(ds.load(p), refresh, proxy) for p in paths])
