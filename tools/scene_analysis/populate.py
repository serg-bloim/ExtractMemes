"""Score a video's scenes for one criterion and write them to the scene database through `SceneStore`."""

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from extract_memes.rule_classifier import Condition

from .store import SceneExistsError, SceneStore, SceneStoreError

_OPS = {">": np.greater, ">=": np.greater_equal, "<": np.less, "<=": np.less_equal}


def production_condition(thresholds: dict[str, list[dict]], criterion: str) -> tuple[str, float] | None:
    """The `(op, value)` the production rule compares `criterion` with, if it does (the first one)."""
    found = thresholds.get(criterion)
    return (found[0]["op"], float(found[0]["value"])) if found else None


def scene_stats(scores: np.ndarray, condition: tuple[str, float] | None) -> dict:
    """Spread of one scene's frame scores and, given a `(op, threshold)` condition, the share of frames meeting it.

    Without a condition `op`, `threshold` and `share_flagged` are None.
    """
    stats = {"op": None, "threshold": None, "min": float(scores.min()), "max": float(scores.max()),
             "mean": float(scores.mean()), "std": float(scores.std()), "share_flagged": None}
    if condition is not None:
        op, threshold = condition
        if op not in _OPS:
            raise ValueError(f"op must be one of {', '.join(_OPS)}, not {op!r}")
        stats.update(op=op, threshold=float(threshold), share_flagged=float(_OPS[op](scores, threshold).mean()))
    return stats


@dataclass
class Result:
    inserted: int = 0
    updated: int = 0
    errors: list[str] = field(default_factory=list)


def populate(store: SceneStore, video_id: str, format_id: str, pts: np.ndarray, rows: np.ndarray,
             row_last: np.ndarray, scores: dict[str, np.ndarray],
             conditions: dict[str, tuple[str, float] | None]) -> Result:
    """Write every scene (rows `rows..row_last`) with the stats of every criterion in `scores`.

    `conditions` gives each criterion's `(op, threshold)` or None. A scene already in the database keeps
    everything but these criteria's stats, which are replaced. Problems (a criterion with non-finite scores
    in a scene, a refused write) are collected in `Result.errors` and the rest is still written.
    """
    result = Result()
    with store.batch():
        for number, (first, last) in enumerate(zip(rows.tolist(), row_last.tolist())):
            stats = {}
            for name, values in scores.items():
                frame_scores = values[first:last + 1]
                if not np.isfinite(frame_scores).all():
                    result.errors.append(f"scene {number} (frames {first}-{last}): {name} has non-finite scores")
                    continue
                stats[name] = scene_stats(frame_scores, conditions.get(name))
            try:
                store.insert_scene(video_id, format_id, first, last, float(pts[first]), float(pts[last]),
                                   last - first + 1, stats)
                result.inserted += 1
            except SceneExistsError:
                try:
                    for name, one in stats.items():
                        store.set_criterion_stats(video_id, format_id, first, name, one)
                    result.updated += 1
                except SceneStoreError as exc:
                    result.errors.append(f"scene {number}: {exc}")
            except SceneStoreError as exc:
                result.errors.append(f"scene {number}: {exc}")
    return result


def open_video(source: str, format_id: str | None, proxy: str | None, progress=None) -> tuple[Path, str, str]:
    """`(video file, video id, format id)`, choosing the format as the labeler does.

    A video with a dataset is pinned to the dataset's exact format. Otherwise `format_id` if given, else
    the labeler page's preselected format (`preferred_format`: at least 25 fps, then the smallest
    resolution, then not AV1).
    """
    from tools.labeling import dataset as ds

    video_id = ds.video_id_from(source)
    dataset_file = ds.dataset_path(video_id)
    if dataset_file.is_file():
        dataset = ds.load(dataset_file)
        return ds.ensure_video(dataset, proxy=proxy, progress=progress), video_id, dataset.video.format_id
    url = ds.canonical_url(video_id)
    if format_id is None:
        format_id = ds.preferred_format(ds.fetch_video_info(url, proxy)["formats"])
        if format_id is None:
            raise ds.DatasetError(f"{url} offers no video formats")
    path, video = ds.download_format(url, format_id, proxy=proxy, progress=progress)
    return path, video_id, video.format_id
