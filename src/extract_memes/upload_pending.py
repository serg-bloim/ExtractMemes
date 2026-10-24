"""Upload the memes of the given videos, then report which went out.

The workflow picks the videos (`playlist_watch pending`, those with status `extracted`) and passes their
ids here; they are uploaded in the order given and the first failure stops the run. The status file is
not touched here: each uploaded id is appended to a "done" file, which the workflow turns into
`uploaded` statuses after syncing with the data branch. The link of each video's Telegram post is
appended to a links file (`<video id> <link>` per line) that lives in the data branch.
"""

import argparse
import os
import re
from collections.abc import Callable
from pathlib import Path

from extract_memes.downloader import SourceInfo, fetch_source_info
from extract_memes.telegram_uploader import TelegramUploader
from extract_memes.uploader import Uploader

DEFAULT_RUNS_DIR = Path("data/runs")
DEFAULT_TEMPLATE_FILE = Path(".github/admin-message.txt")


_MARKDOWN_SPECIAL = re.compile(r"([_*\[\]()~`>#+\-=|{}.!\\])")
_CODE = re.compile(r"(```.*?```|`[^`\n]+`)", re.DOTALL)


def render_admin_message(template: str, video_id: str, post_link: str) -> str:
    """Fill `{video_id}` and `{post_link}` in `template` and return it as Telegram MarkdownV2 (send with `parse_mode="MarkdownV2"`).

    Any other braces are left as written. A ```fenced``` block and `inline code` keep their formatting;
    everything else is escaped, so the template needs no escaping of its own.
    """
    text = template.replace("{video_id}", video_id).replace("{post_link}", post_link)
    parts = _CODE.split(text)
    for i, part in enumerate(parts):
        if i % 2:
            fence = "```" if part.startswith("```") else "`"
            inner = part[len(fence) : -len(fence)]
            parts[i] = fence + re.sub(r"([`\\])", r"\\\1", inner) + fence
        else:
            parts[i] = _MARKDOWN_SPECIAL.sub(r"\\\1", part)
    return "".join(parts)


def upload_pending(
    video_ids: list[str],
    runs_dir: Path,
    uploader: Uploader,
    on_uploaded: Callable[[str, str | None], None] = lambda video_id, link: None,
    fetch_info: Callable[[str], SourceInfo | None] = fetch_source_info,
) -> list[str]:
    """Upload the clean memes of each video in `video_ids` and call `on_uploaded(video_id, link)` right after each.

    A video whose `clean/` folder holds no images (no memes were found; git doesn't keep empty
    folders) counts as uploaded with nothing to post, and has no link. A failure propagates, leaving that video and
    the ones after it pending.
    """
    uploaded = []
    for video_id in video_ids:
        link = None
        source = f"https://youtu.be/{video_id}"
        images = sorted((runs_dir / video_id / "clean").glob("meme_*.png"))
        if images:
            try:
                info = fetch_info(source)
            except Exception as exc:
                print(f"Could not fetch the title and thumbnail of {video_id}: {exc}")
                info = None
            link = uploader.upload_all(images, source, info)
            print(f"Uploaded {len(images)} memes of {video_id}")
        else:
            print(f"No memes to upload for {video_id}")
        on_uploaded(video_id, link)
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
        "--links-file",
        type=Path,
        default=None,
        help="append `<video id> <Telegram post link>` to this file for each uploaded video that has a link",
    )
    parser.add_argument(
        "--admin-chat-id",
        default=None,
        help="Telegram chat to notify about each uploaded video; falls back to TELEGRAM_ADMIN_CHAT_ID, none if unset",
    )
    parser.add_argument(
        "--admin-template-file",
        type=Path,
        default=DEFAULT_TEMPLATE_FILE,
        help="message template used unless the ADMIN_MESSAGE_TEMPLATE env var is set; default: %(default)s",
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

    uploader = TelegramUploader()
    admin_chat = args.admin_chat_id or os.environ.get("TELEGRAM_ADMIN_CHAT_ID")
    template = os.environ.get("ADMIN_MESSAGE_TEMPLATE") or (
        args.admin_template_file.read_text() if admin_chat else ""
    )

    def notify_admin(video_id: str, link: str) -> None:
        # A failed notification must not fail the run: the video is already uploaded.
        try:
            uploader.send_message(admin_chat, render_admin_message(template, video_id, link), parse_mode="MarkdownV2")
        except Exception as exc:
            print(f"Could not notify the admin chat about {video_id}: {exc}")

    def record(video_id: str, link: str | None) -> None:
        args.done_file.parent.mkdir(parents=True, exist_ok=True)
        with args.done_file.open("a") as f:
            f.write(f"{video_id}\n")
        if link and args.links_file:
            args.links_file.parent.mkdir(parents=True, exist_ok=True)
            with args.links_file.open("a") as f:
                f.write(f"{video_id} {link}\n")
        if link and admin_chat:
            notify_admin(video_id, link)

    upload_pending(
        args.video_ids,
        args.runs_dir,
        uploader,
        on_uploaded=record,
        fetch_info=lambda source: fetch_source_info(source, proxy=proxy),
    )


if __name__ == "__main__":
    main()
