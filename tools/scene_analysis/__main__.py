"""Scene score database: `python -m tools.scene_analysis populate <video-id>` from the project root."""

import argparse
import sys
import time
from pathlib import Path

from tools.labeling.index import CACHE_ROOT, build

from . import formats
from . import populate as populate_module
from . import verify as verify_module
from .store import DEFAULT_PATH, SceneStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.scene_analysis", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    pop = sub.add_parser("populate", help="store every scene of a video with the stats of every criterion")
    pop.add_argument("source", help="YouTube URL or video id")
    pop.add_argument("--format-id", help="yt-dlp format for a video with no dataset (default: the labeler's preselection)")
    pop.add_argument("--no-prompt", action="store_true", help="don't ask for the format; use the labeler's preselection")
    pop.add_argument("--proxy", help="proxy for yt-dlp")
    pop.add_argument("--db", type=Path, default=DEFAULT_PATH, help="database file (default: %(default)s)")
    ver = sub.add_parser("verify", help="have Claude judge the scenes nearest the production threshold")
    ver.add_argument("--criterion", default="edge_histogram", help="criterion whose scores are ranked (default: %(default)s)")
    ver.add_argument("--top", type=int, default=100, help="how many scenes to check (default: %(default)s)")
    ver.add_argument("--batch-size", type=int, default=10, help="scenes (two frames each) per Claude call (default: %(default)s)")
    ver.add_argument("--recheck", action="store_true", help="also take scenes that already have a Claude status")
    ver.add_argument("--dbg", action="store_true", help="print the time spent in each stage (database load / select / frames / Claude / verdicts / database save)")
    ver.add_argument("--dry-run", action="store_true", help="list the selected scenes; don't call Claude")
    ver.add_argument("--model", default="claude-haiku-4-5-20251001", help="Claude model (default: %(default)s)")
    ver.add_argument("--effort", default="low", help="Claude effort (default: %(default)s)")
    ver.add_argument("--db", type=Path, default=DEFAULT_PATH, help="database file (default: %(default)s)")
    web = sub.add_parser("browse", help="open a read-only web browser for the scene database")
    web.add_argument("--port", type=int, default=8766, help="port (default: %(default)s)")
    web.add_argument("--host", default="127.0.0.1", help="address to listen on (default: %(default)s)")
    web.add_argument("--db", type=Path, default=DEFAULT_PATH, help="database file (default: %(default)s)")
    args = parser.parse_args(argv)

    if args.command == "browse":
        from .browser import create_app

        print(f"Scene browser: http://{args.host if args.host != '0.0.0.0' else '127.0.0.1'}:{args.port}/  (Ctrl+C to stop)")
        create_app(SceneStore(args.db)).run(host=args.host, port=args.port, threaded=True)
        return 0
    if args.command == "verify":
        return run_verify(args)
    choose = None if args.no_prompt or not sys.stdin.isatty() else formats.choose_with_arrows
    try:
        video_path, video_id, format_id = populate_module.open_video(args.source, args.format_id, args.proxy, choose=choose)
        index = build(video_path, CACHE_ROOT / f"{video_id}_{format_id}")
        names = [c.name for c in index.criteria]
        conditions = {n: populate_module.production_condition(index.thresholds, n) for n in names}
        print(f"\n{video_id} (format {format_id}): {len(index.rows)} scenes, criteria: {', '.join(names)}")
        result = populate_module.populate(SceneStore(args.db), video_id, format_id, index.pts, index.rows,
                                          index.row_last, index.scores, conditions)
    except Exception as exc:  # report any failure, including download and store errors, and exit non-zero
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"{result.inserted} scenes inserted, {result.updated} updated, {result.unchanged} unchanged in {args.db}")
    if result.errors:
        print(f"{len(result.errors)} errors:", file=sys.stderr)
        for line in result.errors:
            print(f"  {line}", file=sys.stderr)
        return 1
    print("no errors")
    return 0


def run_verify(args: argparse.Namespace) -> int:
    from tools.labeling.dataset import DOWNLOADS_DIR

    if args.batch_size < 1:
        print("ERROR: --batch-size must be at least 1", file=sys.stderr)
        return 1
    started = time.perf_counter()
    store = SceneStore(args.db)
    source = verify_module.FrameSource(DOWNLOADS_DIR, CACHE_ROOT)
    result = None
    try:
        with store.batch():  # one session: the file is read once, and written once when the run ends
            selecting = time.perf_counter()
            scenes = verify_module.select(store, args.criterion, args.top, args.recheck)
            select_seconds = time.perf_counter() - selecting
            print(f"{len(scenes)} scenes selected (criterion {args.criterion}, nearest the threshold first)")
            if args.dry_run:
                for scene in scenes:
                    stats = scene["stats"][args.criterion]
                    print(f"  {scene['video_id']}/{scene['format_id']} frames {scene['first_frame']}-{scene['last_frame']}: "
                          f"distance {verify_module.distance_from_threshold(stats):.3f}, min {stats['min']:.3f}, max {stats['max']:.3f}, "
                          f"flagged {stats['share_flagged']:.2f}, check {verify_module.check_of(stats)}")
            else:
                result = verify_module.verify(store, scenes, args.criterion, source,
                                              verify_module.ClaudeJudge(args.model, args.effort), args.batch_size, progress=print)
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        source.close()
    if args.dbg:  # the session has closed, so the database save is included
        print(verify_module.format_timings(store.timings, select_seconds, result, time.perf_counter() - started))
    if result is None:
        return 0
    summary = ", ".join(f"{count} {name}" for name, count in sorted(result.verdicts.items())) or "none"
    print(f"{result.checked} scenes checked ({summary}) in {args.db}")
    if result.errors:
        print(f"{len(result.errors)} errors:", file=sys.stderr)
        for line in result.errors:
            print(f"  {line}", file=sys.stderr)
        return 1
    print("no errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
