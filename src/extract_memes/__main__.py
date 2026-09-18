"""Command-line entrypoint for ExtractMemes."""

import argparse
import os
from pathlib import Path

from extract_memes import batch_cleaner, pipeline


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
    parser.add_argument(
        "--save-high-res",
        action="store_true",
        help=(
            "keep each meme's full-quality frames in <runtime-dir>/<run-name>/high-res/meme_<n>/; "
            "required with --clean-method none, which has nothing else to save"
        ),
    )
    parser.add_argument(
        "--save-timecodes",
        action="store_true",
        help=(
            "write the start timecode of each meme, one per line, to "
            "<runtime-dir>/<run-name>/timecodes.txt in YouTube's chapter format"
        ),
    )
    parser.add_argument(
        "--timecode-offset",
        type=float,
        default=0.0,
        metavar="SECONDS",
        help=(
            "shift every timecode by this many seconds; negative shifts earlier, e.g. -1 starts "
            "each meme a second before it appears (default: %(default)s)"
        ),
    )
    parser.add_argument(
        "--no-images",
        action="store_true",
        help=(
            "stop after the scan: skip the best-quality download and write no images at all. "
            "Pair it with --save-timecodes, whose timecodes then come from the scan frames"
        ),
    )
    parser.add_argument(
        "--clean-method",
        choices=("none", *batch_cleaner.METHODS),
        default=batch_cleaner.DEFAULT_METHOD,
        help=(
            "how to combine each meme's frames into one less distorted image in "
            "<runtime-dir>/<run-name>/clean/; 'none' skips cleaning (default: %(default)s)"
        ),
    )
    parser.add_argument(
        "--upload-to",
        choices=["telegram"],
        default=None,
        help="upload each saved meme image to a messenger chat as the run finishes (default: no upload)",
    )
    parser.add_argument(
        "--telegram-bot-token",
        default=None,
        help="Telegram bot token; falls back to the TELEGRAM_BOT_TOKEN env var. Only applies to --upload-to telegram",
    )
    parser.add_argument(
        "--telegram-chat-id",
        default=None,
        help="Telegram chat id to upload to; falls back to the TELEGRAM_CHAT_ID env var. Only applies to --upload-to telegram",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.source is None:
        parser.print_help()
        return
    if args.no_images and args.save_high_res:
        parser.error("--no-images cannot be combined with --save-high-res")
    if args.upload_to == "telegram":
        if args.no_images:
            parser.error("--upload-to telegram cannot be combined with --no-images")
        bot_token = args.telegram_bot_token or os.environ.get("TELEGRAM_BOT_TOKEN")
        chat_id = args.telegram_chat_id or os.environ.get("TELEGRAM_CHAT_ID")
        if not bot_token or not chat_id:
            parser.error(
                "--upload-to telegram requires --telegram-bot-token/--telegram-chat-id or "
                "TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID"
            )

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
        clean_method=None if args.clean_method == "none" else args.clean_method,
        save_high_res=args.save_high_res,
        save_timecodes=args.save_timecodes,
        timecode_offset=args.timecode_offset,
        no_images=args.no_images,
        upload_to=args.upload_to,
        telegram_bot_token=args.telegram_bot_token,
        telegram_chat_id=args.telegram_chat_id,
    )
    for path in saved:
        print(path)


if __name__ == "__main__":
    main()
