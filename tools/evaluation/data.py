"""Load the labeled datasets with their cached criterion scores, pooled into one sample set."""

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from extract_memes import criteria as criteria_package
from tools.labeling import dataset as ds
from tools.labeling.index import CACHE_ROOT, build

from .truth import IGNORED, ground_truth

SCAN_FPS = 3.0


@dataclass
class Samples:
    """Scanned frames of one or more videos: a score per criterion and a label per frame."""

    scores: dict[str, np.ndarray]
    labels: np.ndarray  # truth.POSITIVE / NEGATIVE / IGNORED
    video: np.ndarray  # video id of each frame
    frame: np.ndarray  # frame index within its video
    ts: np.ndarray  # timestamp in seconds

    def select(self, mask: np.ndarray) -> "Samples":
        return Samples({n: v[mask] for n, v in self.scores.items()}, self.labels[mask], self.video[mask],
                       self.frame[mask], self.ts[mask])

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
    return Samples(
        scores={n: np.load(cache_dir / f"{n}.npy").astype(float) for n in criteria},
        labels=ground_truth(dataset, rows, pts),
        video=np.full(len(rows), dataset.video.id),
        frame=rows,
        ts=pts[rows],
    )


def pool(parts: list[Samples]) -> Samples:
    return Samples(
        {n: np.concatenate([p.scores[n] for p in parts]) for n in parts[0].scores},
        np.concatenate([p.labels for p in parts]),
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
