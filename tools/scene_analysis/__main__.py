"""Scene score database: `python -m tools.scene_analysis populate <url-or-id>` from the project root."""

import argparse
from pathlib import Path

from tools.labeling.index import CACHE_ROOT, build

from . import populate as populate_module
from .store import DEFAULT_PATH, SceneStore


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m tools.scene_analysis", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    pop = sub.add_parser("populate", help="score a video's scenes for a criterion and store them")
    pop.add_argument("source", help="YouTube URL or video id")
    pop.add_argument("--criterion", default="band", help="criterion to score (default: %(default)s)")
    pop.add_argument("--op", choices=(">", ">=", "<", "<="), help="default: the production rule's")
    pop.add_argument("--threshold", type=float, help="default: the production rule's")
    pop.add_argument("--format-id", help="yt-dlp format for a video with no dataset (default: the worst)")
    pop.add_argument("--proxy", help="proxy for yt-dlp")
    pop.add_argument("--db", type=Path, default=DEFAULT_PATH, help="database file (default: %(default)s)")
    args = parser.parse_args(argv)

    if (args.op is None) != (args.threshold is None):
        parser.error("--op and --threshold go together")
    video_path, video_id, format_id = populate_module.open_video(args.source, args.format_id, args.proxy)
    index = build(video_path, CACHE_ROOT / f"{video_id}_{format_id}")
    if args.criterion not in index.scores:
        parser.error(f"unknown criterion {args.criterion!r}; choose from {', '.join(sorted(index.scores))}")
    op, threshold = args.op, args.threshold
    if op is None:
        found = populate_module.production_condition(index.thresholds, args.criterion)
        if found is None:
            parser.error(f"the production rule doesn't use {args.criterion!r}; give --op and --threshold")
        op, threshold = found
    print(f"{video_id} ({format_id}): {len(index.rows)} scenes, {args.criterion} {op} {threshold:g}")
    populate_module.populate(SceneStore(args.db), video_id, format_id, index.pts, index.rows, index.row_last,
                             index.scores[args.criterion], args.criterion, op, threshold, progress=print)


if __name__ == "__main__":
    main()
