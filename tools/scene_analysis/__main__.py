"""Scene score database: `python -m tools.scene_analysis populate <video-id>` from the project root."""

import argparse
import sys
from pathlib import Path

from tools.labeling.index import CACHE_ROOT, build

from . import populate as populate_module
from .store import DEFAULT_PATH, SceneStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.scene_analysis", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    pop = sub.add_parser("populate", help="store every scene of a video with the stats of every criterion")
    pop.add_argument("source", help="YouTube URL or video id")
    pop.add_argument("--format-id", help="yt-dlp format for a video with no dataset (default: the labeler's preselection)")
    pop.add_argument("--proxy", help="proxy for yt-dlp")
    pop.add_argument("--db", type=Path, default=DEFAULT_PATH, help="database file (default: %(default)s)")
    args = parser.parse_args(argv)

    try:
        video_path, video_id, format_id = populate_module.open_video(args.source, args.format_id, args.proxy)
        index = build(video_path, CACHE_ROOT / f"{video_id}_{format_id}")
        names = [c.name for c in index.criteria]
        conditions = {n: populate_module.production_condition(index.thresholds, n) for n in names}
        print(f"\n{video_id} (format {format_id}): {len(index.rows)} scenes, criteria: {', '.join(names)}")
        result = populate_module.populate(SceneStore(args.db), video_id, format_id, index.pts, index.rows,
                                          index.row_last, index.scores, conditions)
    except Exception as exc:  # report any failure, including download and store errors, and exit non-zero
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"{result.inserted} scenes inserted, {result.updated} updated in {args.db}")
    if result.errors:
        print(f"{len(result.errors)} errors:", file=sys.stderr)
        for line in result.errors:
            print(f"  {line}", file=sys.stderr)
        return 1
    print("no errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
