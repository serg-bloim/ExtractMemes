"""Score a video's scenes for one criterion and write them to the scene database through `SceneStore`."""

from collections.abc import Callable
from pathlib import Path

import numpy as np

from extract_memes.rule_classifier import Condition

from .store import SceneExistsError, SceneStore

_OPS = {">": np.greater, ">=": np.greater_equal, "<": np.less, "<=": np.less_equal}


def production_condition(thresholds: dict[str, list[dict]], criterion: str) -> tuple[str, float] | None:
    """The `(op, value)` the production rule compares `criterion` with, if it does (the first one)."""
    found = thresholds.get(criterion)
    return (found[0]["op"], float(found[0]["value"])) if found else None


def scene_stats(scores: np.ndarray, op: str, threshold: float) -> dict:
    """Spread of one scene's frame scores and the share of frames for which `score op threshold` holds."""
    if op not in _OPS:
        raise ValueError(f"op must be one of {', '.join(_OPS)}, not {op!r}")
    return {
        "op": op, "threshold": float(threshold),
        "min": float(scores.min()), "max": float(scores.max()), "mean": float(scores.mean()),
        "std": float(scores.std()), "share_flagged": float(_OPS[op](scores, threshold).mean()),
    }


def populate(store: SceneStore, video_id: str, format_id: str, pts: np.ndarray, rows: np.ndarray,
             row_last: np.ndarray, scores: np.ndarray, criterion: str, op: str, threshold: float,
             progress: Callable[[str], None] = lambda message: None) -> tuple[int, int]:
    """Write every scene (rows `rows..row_last`) with `criterion` stats; returns `(inserted, updated)`.

    A scene already in the database keeps everything but this criterion's stats, which are replaced.
    """
    inserted = updated = 0
    with store.batch():
        for number, (first, last) in enumerate(zip(rows.tolist(), row_last.tolist())):
            stats = scene_stats(scores[first:last + 1], op, threshold)
            try:
                store.insert_scene(video_id, format_id, number, first, last, float(pts[first]), float(pts[last]),
                                   last - first + 1, {criterion: stats})
                inserted += 1
            except SceneExistsError:
                store.set_criterion_stats(video_id, format_id, number, criterion, stats)
                updated += 1
    progress(f"{inserted} scenes inserted, {updated} updated")
    return inserted, updated


def open_video(source: str, format_id: str | None, proxy: str | None, progress=None) -> tuple[Path, str, str]:
    """`(video file, video id, format id)`: the dataset's exact format if the video has one, else the chosen or worst."""
    from extract_memes.downloader import FORMAT_SELECTORS
    from tools.labeling import dataset as ds

    video_id = ds.video_id_from(source)
    dataset_file = ds.dataset_path(video_id)
    if dataset_file.is_file():
        dataset = ds.load(dataset_file)
        return ds.ensure_video(dataset, proxy=proxy, progress=progress), video_id, dataset.video.format_id
    url = source if "/" in source else ds.canonical_url(video_id)
    path, video = ds.download_format(url, format_id or FORMAT_SELECTORS["worst"], proxy=proxy, progress=progress)
    return path, video_id, video.format_id
