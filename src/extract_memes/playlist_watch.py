"""Check a playlist for the oldest video not yet recorded as processed.

`find_next_unprocessed` assumes `video_ids` is newest-first, true for a channel's auto-generated
Uploads playlist — not for an arbitrarily (hand-)ordered playlist.
"""

import argparse
from pathlib import Path

DEFAULT_COUNT = 8
DEFAULT_PROCESSED_FILE = Path("data/processed_vids.txt")


def list_playlist_video_ids(playlist_url: str, count: int) -> list[str]:
    """Return up to `count` video ids from `playlist_url`, metadata only, newest-first."""
    # Imported lazily so importing this module has no import-time side effects.
    import yt_dlp

    options = {
        "extract_flat": "in_playlist",
        "playlistend": count,
        "quiet": True,
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(playlist_url, download=False)
    return [entry["id"] for entry in info["entries"]]


def read_processed(path: Path) -> set[str]:
    """Return the set of video ids recorded in `path`, or an empty set if it doesn't exist."""
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text().splitlines() if line.strip()}


def append_processed(path: Path, video_id: str) -> None:
    """Record `video_id` as processed by appending it to `path`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(f"{video_id}\n")


def find_next_unprocessed(video_ids: list[str], processed: set[str]) -> str | None:
    """Return the oldest id in `video_ids` not in `processed`, or `None` if all are processed."""
    for video_id in reversed(video_ids):
        if video_id not in processed:
            return video_id
    return None


def _cmd_find(args: argparse.Namespace) -> None:
    video_ids = list_playlist_video_ids(args.playlist_url, args.count)
    processed = read_processed(args.processed_file)
    next_id = find_next_unprocessed(video_ids, processed)
    if next_id is not None:
        print(next_id)


def _cmd_mark_processed(args: argparse.Namespace) -> None:
    append_processed(args.processed_file, args.video_id)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m extract_memes.playlist_watch",
        description="Check a playlist for the oldest video not yet processed.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    find_parser = subparsers.add_parser(
        "find", help="print the oldest unprocessed video's id, or nothing if there is none"
    )
    find_parser.add_argument("--playlist-url", required=True)
    find_parser.add_argument("--count", type=int, default=DEFAULT_COUNT, help="default: %(default)s")
    find_parser.add_argument(
        "--processed-file", type=Path, default=DEFAULT_PROCESSED_FILE, help="default: %(default)s"
    )
    find_parser.set_defaults(func=_cmd_find)

    mark_parser = subparsers.add_parser("mark-processed", help="record a video id as processed")
    mark_parser.add_argument("video_id")
    mark_parser.add_argument(
        "--processed-file", type=Path, default=DEFAULT_PROCESSED_FILE, help="default: %(default)s"
    )
    mark_parser.set_defaults(func=_cmd_mark_processed)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
