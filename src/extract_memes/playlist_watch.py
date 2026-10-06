"""Check a playlist for the oldest video not yet recorded as processed.

`find_next_unprocessed` assumes `video_ids` is newest-first, true for a channel's auto-generated
Uploads playlist — not for an arbitrarily (hand-)ordered playlist.
"""

import argparse
import datetime
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path

DEFAULT_LOOKBACK_DAYS = 365
DEFAULT_PROCESSED_FILE = Path("data/processed_vids.txt")
DEFAULT_DATES_CACHE = Path("data/upload_dates.json")


def parse_since(value: str) -> datetime.date:
    """Parse `YYYY-MM-DD` (or yt-dlp's `YYYYMMDD`) into a date."""
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"invalid date {value!r}, expected YYYY-MM-DD")


def default_since() -> datetime.date:
    return datetime.date.today() - datetime.timedelta(days=DEFAULT_LOOKBACK_DAYS)


def load_upload_dates(path: Path) -> dict[str, str]:
    """Return the `video id -> YYYY-MM-DD` cache in `path`, or `{}` if it is missing, empty or invalid."""
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    try:
        dates = json.loads(text)
    except json.JSONDecodeError:
        dates = None
    if not isinstance(dates, dict):
        print(f"Ignoring upload-date cache {path}: not a JSON object", file=sys.stderr)
        return {}
    return {str(video_id): str(date) for video_id, date in dates.items()}


def save_upload_dates(path: Path, dates: dict[str, str]) -> None:
    """Write the upload-date cache as indented JSON with sorted keys, creating parent directories.

    The file is replaced in one step, so a process killed mid-write leaves the old cache intact.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(dates, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _upload_date(
    entry: dict, ydl, upload_dates: dict[str, str], on_new_date: Callable[[], None] | None = None
) -> datetime.date | None:
    """Return the entry's upload date, fetching the video's metadata if neither the flat entry nor the cache has it.

    A date that had to be fetched is added to `upload_dates`, then `on_new_date` is called.
    """
    upload_date = entry.get("upload_date")
    if not upload_date:
        timestamp = entry.get("timestamp")
        if timestamp:
            return datetime.datetime.fromtimestamp(timestamp, datetime.timezone.utc).date()
        if entry["id"] in upload_dates:
            return parse_since(upload_dates[entry["id"]])
        info = ydl.extract_info(entry["id"], download=False)
        upload_date = info.get("upload_date")
        if upload_date:
            upload_dates[entry["id"]] = parse_since(upload_date).isoformat()
            if on_new_date is not None:
                on_new_date()
    return parse_since(upload_date) if upload_date else None


def list_playlist_video_ids(
    playlist_url: str,
    since: datetime.date,
    proxy: str | None = None,
    upload_dates: dict[str, str] | None = None,
    on_new_date: Callable[[], None] | None = None,
) -> list[str]:
    """Return the ids of videos in `playlist_url` uploaded on or after `since`, newest-first.

    Walks the playlist from the newest entry and stops at the first video uploaded before `since`.
    A video whose upload date can't be determined is kept. `proxy` (e.g.
    `socks5h://127.0.0.1:1080` or an `http://` URL), when given, is passed straight through to
    yt-dlp, same as `downloader.download`'s `proxy` parameter.

    `upload_dates` is a `video id -> YYYY-MM-DD` cache: an id found there is not fetched, and every
    date that is fetched is added to it in place, so the caller still has them if this raises.
    `on_new_date`, when given, is called right after each such addition, so the caller can persist
    the cache one video at a time.
    """
    # Imported lazily so importing this module has no import-time side effects.
    import yt_dlp

    if upload_dates is None:
        upload_dates = {}
    options = {
        "extract_flat": "in_playlist",
        "lazy_playlist": True,
        "quiet": True,
        # Only deno is enabled by default; without a runtime yt-dlp warns on every extraction.
        "js_runtimes": {"node": {}},
    }
    if proxy:
        options["proxy"] = proxy
    video_ids = []
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(playlist_url, download=False)
        for entry in info["entries"]:
            uploaded = _upload_date(entry, ydl, upload_dates, on_new_date)
            if uploaded is not None and uploaded < since:
                break
            video_ids.append(entry["id"])
    return video_ids


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
    proxy = args.proxy or os.environ.get("EXTRACT_MEMES_PROXY")
    if args.since is None:
        args.since = default_since()
    upload_dates = load_upload_dates(args.dates_cache)
    # Saved after every fetched date, not at the end: a cancelled run is killed, so a `finally`
    # may never run.
    video_ids = list_playlist_video_ids(
        args.playlist_url,
        args.since,
        proxy=proxy,
        upload_dates=upload_dates,
        on_new_date=lambda: save_upload_dates(args.dates_cache, upload_dates),
    )
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
    find_parser.add_argument(
        "--since",
        type=parse_since,
        default=None,
        help=(
            "only consider videos uploaded on or after this date (YYYY-MM-DD); "
            f"default: {DEFAULT_LOOKBACK_DAYS} days ago"
        ),
    )
    find_parser.add_argument(
        "--processed-file", type=Path, default=DEFAULT_PROCESSED_FILE, help="default: %(default)s"
    )
    find_parser.add_argument(
        "--dates-cache",
        type=Path,
        default=DEFAULT_DATES_CACHE,
        help="JSON file caching each video's upload date between runs; default: %(default)s",
    )
    find_parser.add_argument(
        "--proxy",
        default=None,
        help=(
            "proxy URL for yt-dlp's playlist fetch (e.g. socks5h://127.0.0.1:1080 or an http:// "
            "URL); falls back to the EXTRACT_MEMES_PROXY env var"
        ),
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
