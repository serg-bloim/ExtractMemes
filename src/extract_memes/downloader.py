"""Fetch a source video at a quality tier, or pass a local video file straight through."""

from pathlib import Path
from typing import Literal

# yt-dlp format selectors for each quality tier. YouTube no longer serves pre-muxed formats, so pick
# the worst/best format that contains video (audio isn't needed). See ADR 006.
FORMAT_SELECTORS: dict[str, str] = {
    "worst": "wv*[ext=mp4]/wv*",
    "best": "bv*[ext=mp4]/bv*",
}


def download(source: str, quality: Literal["worst", "best"], dest_dir: Path) -> Path:
    """Return a local video file for `source` at the requested quality tier.

    An existing local file is returned unchanged. Anything else is downloaded with yt-dlp to
    `dest_dir/<video id>_<quality>.<ext>`.
    """
    if Path(source).is_file():
        return Path(source)

    # Imported lazily so local-file runs, `--help`, and tests have no import-time side effects.
    import static_ffmpeg
    import yt_dlp

    dest_dir.mkdir(parents=True, exist_ok=True)
    # Puts ffmpeg on PATH so yt-dlp can remux HLS output into a real MP4 container.
    static_ffmpeg.add_paths()

    options = {
        "format": FORMAT_SELECTORS[quality],
        "outtmpl": str(dest_dir / f"%(id)s_{quality}.%(ext)s"),
        "js_runtimes": {"node": {}},
        "quiet": True,
        "noprogress": True,
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(source, download=True)
            return Path(ydl.prepare_filename(info))
    except Exception as exc:
        raise RuntimeError(f"Failed to download {source!r} at {quality!r} quality: {exc}") from exc
