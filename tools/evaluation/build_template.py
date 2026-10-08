"""Build the reference data of a criterion from the labeled datasets: `python -m tools.evaluation.build_template edge_histogram`.

The reference is the mean and standard deviation of the criterion's features over every frame inside
a marked meme window of every dataset (the positives of the evaluation's ground truth).
"""

import argparse
import json
from pathlib import Path

import numpy as np

from extract_memes.criteria import DATA_DIR, edge_histogram
from tools.labeling import dataset as ds

from .data import load_truth
from .truth import POSITIVE

TEMPLATES = {"edge_histogram": (edge_histogram, edge_histogram.REFERENCE_FILE)}


def summarize(rows: np.ndarray, videos: list[str]) -> dict:
    """The JSON content for feature rows (one per meme frame)."""
    return {"frames": int(len(rows)), "videos": sorted(videos),
            "mean": [round(float(v), 6) for v in rows.mean(axis=0)],
            "std": [round(float(v), 6) for v in rows.std(axis=0)]}


def meme_features(dataset: ds.Dataset, features, proxy: str | None = None) -> np.ndarray:
    """`features(frame)` for every scanned frame inside a marked meme window of `dataset`."""
    rows, labels, _ = load_truth(dataset, proxy)
    wanted = {int(f) for f in rows[labels == POSITIVE]}
    video_path = ds.ensure_video(dataset, proxy=proxy)
    return np.array([features(frame) for _, _, frame in ds.iter_frames(video_path, wanted.__contains__)])


def build(name: str, out_dir: Path = DATA_DIR, proxy: str | None = None) -> dict:
    module, file_name = TEMPLATES[name]
    parts, videos = [], []
    for entry in ds.list_datasets():
        dataset = ds.load(ds.dataset_path(entry["id"]))
        rows = meme_features(dataset, module.features, proxy)
        print(f"{entry['id']}: {len(rows)} meme frames")
        parts.append(rows)
        videos.append(entry["id"])
    if not parts:
        raise SystemExit("No datasets found")
    content = summarize(np.concatenate(parts), videos)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / file_name).write_text(json.dumps(content, indent=1) + "\n")
    print(f"Wrote {out_dir / file_name} ({content['frames']} frames from {', '.join(videos)})")
    return content


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m tools.evaluation.build_template", description=__doc__)
    parser.add_argument("name", choices=sorted(TEMPLATES))
    parser.add_argument("--proxy", help="proxy for yt-dlp, if a video must be downloaded")
    args = parser.parse_args(argv)
    build(args.name, proxy=args.proxy)


if __name__ == "__main__":
    main()
