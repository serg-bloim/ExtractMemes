"""Manual yt-dlp experiments to run one at a time from the IDE.

Nothing is downloaded and nothing is written to disk: each run asks YouTube for a video's metadata
and prints it, so it needs network access (and a proxy, if you use one: set the
EXTRACT_MEMES_PROXY env var). The functions are named `test_*` only so IDE pytest integrations show
a run icon; they assert nothing, and a bare `pytest` collects nothing from here.

`python playground/ytdlp_playground.py` runs `test_list_formats()`.
"""

import os

import yt_dlp

# The video to inspect; change it to look at another one.
VIDEO_URL = "https://www.youtube.com/watch?v=FtU4MuksCzE"


def _size(fmt: dict) -> str:
    size = fmt.get("filesize") or fmt.get("filesize_approx")
    return f"{size / 1024 / 1024:.1f}MiB" if size else "?"


def list_formats(url: str, proxy: str | None = None) -> list[dict]:
    """Return every format yt-dlp offers for `url`, worst to best, without downloading."""
    options = {"quiet": True, "js_runtimes": {"node": {}}}
    if proxy:
        options["proxy"] = proxy
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)
    return info.get("formats", [])


def test_list_formats():
    formats = list_formats(VIDEO_URL, proxy=os.environ.get("EXTRACT_MEMES_PROXY"))
    print(f"{len(formats)} formats for {VIDEO_URL}")
    print(f"{'ID':<10}{'EXT':<6}{'RES':<11}{'FPS':<5}{'VCODEC':<16}{'ACODEC':<14}{'PROTO':<8}{'SIZE':<10}NOTE")
    for fmt in formats:
        print(
            f"{fmt['format_id']:<10}{fmt.get('ext', '?'):<6}{fmt.get('resolution') or '?':<11}"
            f"{fmt.get('fps') or '':<5}{(fmt.get('vcodec') or '?')[:15]:<16}"
            f"{(fmt.get('acodec') or '?')[:13]:<14}{(fmt.get('protocol') or '?')[:7]:<8}"
            f"{_size(fmt):<10}{fmt.get('format_note') or ''}"
        )


if __name__ == "__main__":
    test_list_formats()
