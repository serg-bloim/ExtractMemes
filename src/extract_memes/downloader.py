"""Fetch a source video at a quality tier, or pass a local video file straight through."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from tqdm import tqdm

# yt-dlp format selectors for each quality tier. YouTube no longer serves pre-muxed formats, so pick
# the worst/best format that contains video (audio isn't needed). See ADR 006. AV1 is skipped when
# any other codec is offered, because OpenCV's FFmpeg decodes it only with hardware acceleration,
# which a CI runner lacks; if AV1 is all there is, it is still taken. Each tier prefers mp4 within
# each of those two groups.
FORMAT_SELECTORS: dict[str, str] = {
    "worst": "wv*[vcodec!^=av01][ext=mp4]/wv*[vcodec!^=av01]/wv*[ext=mp4]/wv*",
    "best": "bv*[vcodec!^=av01][ext=mp4]/bv*[vcodec!^=av01]/bv*[ext=mp4]/bv*",
}


@dataclass(frozen=True)
class SourceInfo:
    """What the source video is called and what it looks like, for posting alongside its memes."""

    title: str | None = None
    thumbnail_url: str | None = None


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
    progress_delta: float | None = None,
) -> Path:
    """Return a local video file for `source` at the requested quality tier.

    An existing local file is returned unchanged. Anything else is downloaded with yt-dlp to
    `dest_dir/<video id>_<quality>.<ext>`, showing a `tqdm` progress bar. `proxy` (e.g.
    `socks5h://127.0.0.1:1080` or an `http://` URL), when given, is passed straight through to
    yt-dlp; it's ignored for a local-file source, same as `quality` and `dest_dir`. `progress_delta`,
    when given, is the minimum number of seconds between progress updates, applied to both the
    `tqdm` bar and yt-dlp's own progress events.
    """
    if Path(source).is_file():
        return Path(source)

    # Imported lazily so local-file runs, `--help`, and tests have no import-time side effects.
    import static_ffmpeg
    import yt_dlp

    dest_dir.mkdir(parents=True, exist_ok=True)
    # Puts ffmpeg on PATH so yt-dlp can remux HLS output into a real MP4 container.
    static_ffmpeg.add_paths()

    bar_options = {} if progress_delta is None else {"mininterval": progress_delta}
    with tqdm(
        desc=f"Downloading ({quality})", unit="B", unit_scale=True, unit_divisor=1024, **bar_options
    ) as bar:
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
        if progress_delta:
            options["progress_delta"] = progress_delta
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(source, download=True)
                return Path(ydl.prepare_filename(info))
        except Exception as exc:
            raise RuntimeError(f"Failed to download {source!r} at {quality!r} quality: {exc}") from exc


def fetch_source_info(source: str, proxy: str | None = None) -> SourceInfo | None:
    """Return the title and thumbnail URL of a URL `source`, or `None` for a local file.

    Makes a metadata-only yt-dlp request (nothing is downloaded). Raises if that request fails.
    """
    if Path(source).is_file():
        return None

    import yt_dlp

    options = {"quiet": True, "noprogress": True, "skip_download": True, "js_runtimes": {"node": {}}}
    if proxy:
        options["proxy"] = proxy
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(source, download=False)
    return SourceInfo(title=info.get("title"), thumbnail_url=info.get("thumbnail"))
