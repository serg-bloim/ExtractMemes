"""Command-line entrypoint for ExtractMemes."""

import argparse
from pathlib import Path

from extract_memes import pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="extract-memes",
        description=(
            "Extract meme images from a video known to contain them: scan for glitch-framed "
            "meme cards and save those frames from a best-quality copy under "
            "<runtime-dir>/<run-name>/high-res/."
        ),
    )
    parser.add_argument("source", nargs="?", help="YouTube URL or local video file path")
    parser.add_argument(
        "--fps",
        type=float,
        default=2.0,
        help="frames to sample per second of video (default: %(default)s)",
    )
    parser.add_argument(
        "--downloads-dir",
        type=Path,
        default=Path("downloads"),
        help="where downloaded videos go (default: %(default)s)",
    )
    parser.add_argument(
        "--runtime-dir",
        type=Path,
        default=Path(".runtime"),
        help="where per-run frames and saved memes go (default: %(default)s)",
    )
    parser.add_argument(
        "--run-name",
        help="run folder name under the runtime dir (default: derived from the source)",
    )
    parser.add_argument(
        "--classifier",
        choices=["heuristic", "claude"],
        default="heuristic",
        help="classifier to use: heuristic (fast, offline) or claude (requires `claude` CLI) (default: %(default)s)",
    )
    parser.add_argument(
        "--classifier-model",
        default="claude-haiku-4-5-20251001",
        help="Claude model used to classify frames; only applies to --classifier claude (default: %(default)s)",
    )
    parser.add_argument(
        "--classifier-effort",
        choices=["low", "medium", "high", "xhigh", "max"],
        default="low",
        help="Claude effort level used to classify frames; only applies to --classifier claude (default: %(default)s)",
    )
    parser.add_argument(
        "--save-frames",
        action="store_true",
        help="write every sampled frame to <runtime-dir>/<run-name>/frames/ for inspection",
    )
    parser.add_argument(
        "--save-low-res",
        action="store_true",
        help="write scan-quality copies to <runtime-dir>/<run-name>/low-res/ as memes are found",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.source is None:
        parser.print_help()
        return

    saved = pipeline.run(
        args.source,
        downloads_dir=args.downloads_dir,
        runtime_dir=args.runtime_dir,
        run_name=args.run_name,
        fps=args.fps,
        classifier_type=args.classifier,
        classifier_model=args.classifier_model,
        classifier_effort=args.classifier_effort,
        save_frames=args.save_frames,
        save_low_res=args.save_low_res,
    )
    for path in saved:
        print(path)


if __name__ == "__main__":
    main()
