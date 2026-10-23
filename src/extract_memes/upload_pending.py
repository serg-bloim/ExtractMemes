"""Upload the memes of the given videos, then report which went out.

The workflow picks the videos (`playlist_watch pending`, those with status `extracted`) and passes their
ids here; they are uploaded in the order given and the first failure stops the run. The status file is
not touched here: each uploaded id is appended to a "done" file, which the workflow turns into
`uploaded` statuses after syncing with the data branch.
"""

import argparse
import os
from collections.abc import Callable
from pathlib import Path

from extract_memes.downloader import SourceInfo, fetch_source_info
from extract_memes.telegram_uploader import TelegramUploader
from extract_memes.uploader import Uploader

DEFAULT_RUNS_DIR = Path("data/runs")


def upload_pending(
    video_ids: list[str],
    runs_dir: Path,
    uploader: Uploader,
    on_uploaded: Callable[[str], None] = lambda video_id: None,
    fetch_info: Callable[[str], SourceInfo | None] = fetch_source_info,
) -> list[str]:
    """Upload the clean memes of each video in `video_ids` and call `on_uploaded(video_id)` right after each.

    A video whose `clean/` folder holds no images (no memes were found; git doesn't keep empty
    folders) counts as uploaded with nothing to post. A failure propagates, leaving that video and
    the ones after it pending.
    """
    uploaded = []
    for video_id in video_ids:
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
    parser.add_argument("video_ids", nargs="+", metavar="video_id", help="videos to upload, in this order")
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR, help="default: %(default)s")
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
        args.video_ids,
        args.runs_dir,
        TelegramUploader(),
        on_uploaded=record,
        fetch_info=lambda source: fetch_source_info(source, proxy=proxy),
    )


if __name__ == "__main__":
    main()
