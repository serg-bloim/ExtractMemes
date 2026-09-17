"""Command-line entrypoint for ExtractMemes."""

import argparse
from pathlib import Path

from extract_memes import pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="extract-memes",
        description=(
            "Extract meme images from a YouTube video known to contain them: scan a "
            "worst-quality copy for glitch-framed meme cards with Claude, then save those "
            "frames from a best-quality copy under <runtime-dir>/<run-name>/saved/."
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
        "--classifier-model",
        default="claude-haiku-4-5-20251001",
        help="Claude model used to classify frames (default: %(default)s)",
    )
    parser.add_argument(
        "--classifier-effort",
        choices=["low", "medium", "high", "xhigh", "max"],
        default="low",
        help="Claude effort level used to classify frames (default: %(default)s)",
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
        classifier_model=args.classifier_model,
        classifier_effort=args.classifier_effort,
    )
    for path in saved:
        print(path)


if __name__ == "__main__":
    main()
