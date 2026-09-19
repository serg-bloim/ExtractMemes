"""Fetch a source video at a quality tier, or pass a local video file straight through."""

from pathlib import Path
from typing import Literal

from tqdm import tqdm

# yt-dlp format selectors for each quality tier. YouTube no longer serves pre-muxed formats, so pick
# the worst/best format that contains video (audio isn't needed). See ADR 006.
FORMAT_SELECTORS: dict[str, str] = {
    "worst": "wv*[ext=mp4]/wv*",
    "best": "bv*[ext=mp4]/bv*",
}


def _progress_hook(bar: tqdm):
    """Drive `bar` from yt-dlp's progress_hooks events."""

    def hook(status: dict) -> None:
        if status["status"] == "downloading":
            total = status.get("total_bytes") or status.get("total_bytes_estimate")
            if total:
                bar.total = total
            bar.update(status.get("downloaded_bytes", 0) - bar.n)
        elif status["status"] == "finished" and bar.total:
            bar.update(bar.total - bar.n)

    return hook


def download(
    source: str,
    quality: Literal["worst", "best"],
    dest_dir: Path,
    proxy: str | None = None,
) -> Path:
    """Return a local video file for `source` at the requested quality tier.

    An existing local file is returned unchanged. Anything else is downloaded with yt-dlp to
    `dest_dir/<video id>_<quality>.<ext>`, showing a `tqdm` progress bar. `proxy` (e.g.
    `socks5h://127.0.0.1:1080` or an `http://` URL), when given, is passed straight through to
    yt-dlp; it's ignored for a local-file source, same as `quality` and `dest_dir`.
    """
    if Path(source).is_file():
        return Path(source)

    # Imported lazily so local-file runs, `--help`, and tests have no import-time side effects.
    import static_ffmpeg
    import yt_dlp

    dest_dir.mkdir(parents=True, exist_ok=True)
    # Puts ffmpeg on PATH so yt-dlp can remux HLS output into a real MP4 container.
    static_ffmpeg.add_paths()

    with tqdm(desc=f"Downloading ({quality})", unit="B", unit_scale=True, unit_divisor=1024) as bar:
        options = {
            "format": FORMAT_SELECTORS[quality],
            "outtmpl": str(dest_dir / f"%(id)s_{quality}.%(ext)s"),
            "js_runtimes": {"node": {}},
            "quiet": True,
            "noprogress": True,
            "progress_hooks": [_progress_hook(bar)],
        }
        if proxy:
            options["proxy"] = proxy
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(source, download=True)
                return Path(ydl.prepare_filename(info))
        except Exception as exc:
            raise RuntimeError(f"Failed to download {source!r} at {quality!r} quality: {exc}") from exc
