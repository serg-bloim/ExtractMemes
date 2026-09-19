"""Fetch a source video at a quality tier -- whole, or just some ranges of it."""

from collections.abc import Sequence
from contextlib import nullcontext
from pathlib import Path
from typing import Literal

from tqdm import tqdm

from extract_memes import socks_bridge

# yt-dlp format selectors for each quality tier. YouTube no longer serves pre-muxed formats, so pick
# the worst/best format that contains video (audio isn't needed). See ADR 006.
FORMAT_SELECTORS: dict[str, str] = {
    "worst": "wv*[ext=mp4]/wv*",
    "best": "bv*[ext=mp4]/bv*",
}

SECTION_FORMAT_SELECTOR = "bv*[ext=mp4][protocol=https]"
"""A progressive mp4, never HLS.

`https` because a range is fetched by seeking into the file: against an HLS playlist ffmpeg reads
the whole thing and can still cut an empty section. `mp4` because the container picks the
re-encoder, and webm would mean a painfully slow VP9 encode. See ADR 019.
"""

SECTION_ENCODE_ARGS = ["-c:v", "libx264", "-crf", "18", "-preset", "veryfast"]
"""Visually lossless settings for the re-encode that exact cuts force on us. See ADR 019."""


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


def _section_progress_hook(bar: tqdm):
    """Drive `bar` one step per finished section.

    yt-dlp's ffmpeg downloader -- the only one that can fetch a range -- reports no byte progress
    at all, just a `finished` event per section, so `_progress_hook` has nothing to work with here.
    """

    def hook(status: dict) -> None:
        if status["status"] == "finished":
            bar.update(1)

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


def download_sections(
    source: str,
    ranges: Sequence[tuple[float, float]],
    dest_dir: Path,
    proxy: str | None = None,
) -> list[tuple[Path, float]]:
    """Download only `ranges` of `source` at best quality; return a file and its start per range.

    Each range is `(start_seconds, end_seconds)`, and each becomes one file under `dest_dir` named
    after the range, so re-running the same ranges reuses what's already there. The returned start
    is the second the file actually begins at -- exact, because the cut is re-encoded rather than
    stream-copied (ADR 019) -- so a caller can turn a position inside the file back into a position
    in the whole video by adding it.

    `proxy` is passed to yt-dlp as-is. A SOCKS proxy additionally gets a loopback HTTP bridge for
    ffmpeg, which cannot speak SOCKS and would otherwise connect direct without saying so.
    """
    if not ranges:
        raise ValueError("download_sections needs at least one range")

    # Imported lazily so local-file runs, `--help`, and tests have no import-time side effects.
    import static_ffmpeg
    import yt_dlp

    dest_dir.mkdir(parents=True, exist_ok=True)
    # Sections are cut by ffmpeg itself here, not just remuxed with it.
    static_ffmpeg.add_paths()

    sections = [
        {"start_time": float(start), "end_time": float(end), "index": index}
        for index, (start, end) in enumerate(ranges)
    ]
    bridge = socks_bridge.serve(proxy) if socks_bridge.is_socks(proxy) else nullcontext(None)
    with (
        bridge as bridge_url,
        tqdm(total=len(sections), desc="Downloading (sections)", unit="section") as bar,
    ):
        downloader_args = {"ffmpeg_o": SECTION_ENCODE_ARGS}
        if bridge_url:
            downloader_args["ffmpeg_i"] = ["-http_proxy", bridge_url]
        options = {
            "format": SECTION_FORMAT_SELECTOR,
            "outtmpl": str(dest_dir / "%(id)s_best_%(section_start)d-%(section_end)d.%(ext)s"),
            "download_ranges": lambda info, ydl: sections,
            # Without this yt-dlp stream-copies, and the cut slips back to the previous keyframe by
            # an amount nothing downstream can recover. See ADR 019.
            "force_keyframes_at_cuts": True,
            "external_downloader_args": downloader_args,
            "js_runtimes": {"node": {}},
            "quiet": True,
            "noprogress": True,
            "progress_hooks": [_section_progress_hook(bar)],
        }
        if proxy:
            options["proxy"] = proxy
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(source, download=True)
                return [
                    (Path(done["filepath"]), float(done["section_start"]))
                    for done in info["requested_downloads"]
                ]
        except Exception as exc:
            raise RuntimeError(
                f"Failed to download sections {list(ranges)!r} of {source!r}: {exc}"
            ) from exc
