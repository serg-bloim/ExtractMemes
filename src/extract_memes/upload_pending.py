"""Upload the memes of videos whose extraction finished but whose upload hasn't, then report which went out.

Videos with status `extracted` (see `playlist_watch`) are uploaded oldest first, up to a limit, and the
first failure stops the run. The status file is not touched here: each uploaded id is appended to a
"done" file, which the workflow turns into `uploaded` statuses after syncing with the data branch.
"""

import argparse
import os
from collections.abc import Callable
from pathlib import Path

from extract_memes.downloader import SourceInfo, fetch_source_info
from extract_memes.playlist_watch import DEFAULT_PROCESSED_FILE, STATUS_EXTRACTED, read_processed
from extract_memes.telegram_uploader import TelegramUploader
from extract_memes.uploader import Uploader

DEFAULT_LIMIT = 5
DEFAULT_RUNS_DIR = Path("data/runs")


def pending_video_ids(processed: dict[str, str], limit: int) -> list[str]:
    """Return up to `limit` ids with status `extracted`, in file order (oldest first)."""
    return [vid for vid, status in processed.items() if status == STATUS_EXTRACTED][:limit]


def upload_pending(
    processed_file: Path,
    runs_dir: Path,
    uploader: Uploader,
    limit: int = DEFAULT_LIMIT,
    on_uploaded: Callable[[str], None] = lambda video_id: None,
    fetch_info: Callable[[str], SourceInfo | None] = fetch_source_info,
) -> list[str]:
    """Upload the clean memes of each pending video and call `on_uploaded(video_id)` right after each.

    A video whose `clean/` folder holds no images (no memes were found; git doesn't keep empty
    folders) counts as uploaded with nothing to post. A failure propagates, leaving that video and
    the ones after it pending.
    """
    uploaded = []
    for video_id in pending_video_ids(read_processed(processed_file), limit):
        source = f"https://youtu.be/{video_id}"
        images = sorted((runs_dir / video_id / "clean").glob("meme_*.png"))
        if images:
            try:
                info = fetch_info(source)
            except Exception as exc:
                print(f"Could not fetch the title and thumbnail of {video_id}: {exc}")
                info = None
            uploader.upload_all(images, source, info)
            print(f"Uploaded {len(images)} memes of {video_id}")
        else:
            print(f"No memes to upload for {video_id}")
        on_uploaded(video_id)
        uploaded.append(video_id)
    return uploaded


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m extract_memes.upload_pending",
        description="Upload the memes of extracted videos to Telegram.",
    )
    parser.add_argument("--processed-file", type=Path, default=DEFAULT_PROCESSED_FILE, help="default: %(default)s")
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR, help="default: %(default)s")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="most videos per run (default: %(default)s)")
    parser.add_argument(
        "--done-file",
        type=Path,
        required=True,
        help="append each uploaded video id to this file, one per line, as soon as it is uploaded",
    )
    parser.add_argument(
        "--proxy",
        default=None,
        help="proxy URL for fetching titles and thumbnails; falls back to the EXTRACT_MEMES_PROXY env var",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    proxy = args.proxy or os.environ.get("EXTRACT_MEMES_PROXY")

    def record(video_id: str) -> None:
        args.done_file.parent.mkdir(parents=True, exist_ok=True)
        with args.done_file.open("a") as f:
            f.write(f"{video_id}\n")

    upload_pending(
        args.processed_file,
        args.runs_dir,
        TelegramUploader(),
        limit=args.limit,
        on_uploaded=record,
        fetch_info=lambda source: fetch_source_info(source, proxy=proxy),
    )


if __name__ == "__main__":
    main()
