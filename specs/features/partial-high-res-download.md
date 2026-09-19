---
title: "Partial High-Res Download"
status: ready
created: 2026-09-19
updated: 2026-09-19
author: ""
depends-on: ["video-download", "extraction-pipeline"]
---

# Partial High-Res Download

## Problem Statement

The extraction stage downloads the whole source video a second time at best quality, then reads
only a ±`window_seconds` batch of frames around each flagged timestamp. On a 20-minute 1080p
compilation that is hundreds of megabytes fetched to decode a few seconds per meme, and in the
scheduled workflow every one of those bytes crosses a home SOCKS proxy. The frames the pipeline
actually reads are a small, known fraction of the file, and they are known before the download
starts — the scan pass has already produced the timestamps.

## User Story

**Primary:**
As someone running the pipeline on a long video, I want the best-quality pass to fetch only the
moments that contain memes, so that a run finishes in a fraction of the bandwidth and time.

**Secondary:**
As the maintainer of the scheduled workflow, I want that saving to hold when downloads go through
the SOCKS proxy, so that the runner does not fall back to fetching the whole file — or, worse,
bypass the proxy entirely.

## Acceptance Criteria

- [ ] AC1: `src/extract_memes/downloader.py` exposes
      `download_sections(source: str, ranges: Sequence[tuple[float, float]], dest_dir: Path,
      proxy: str | None = None) -> list[tuple[Path, float]]`, returning one
      `(file, exact start second)` per requested range, in the order given. An empty `ranges`
      raises `ValueError`.
- [ ] AC2: Sections are fetched with yt-dlp's `download_ranges` and `force_keyframes_at_cuts=True`,
      so each file's first frame is the frame at its requested start and
      `absolute = section_start + local` holds. Format selector is `bv*[ext=mp4]`
      (`SECTION_FORMAT_SELECTOR`), and the cut is re-encoded with
      `SECTION_ENCODE_ARGS = ["-c:v", "libx264", "-crf", "12", "-preset", "veryfast"]`, passed as
      `external_downloader_args={"ffmpeg_o": …}`.
- [ ] AC3: Section files land at `dest_dir/<id>_best_<start>-<end>.<ext>` with integer-second
      bounds, e.g. `downloads/AElGyY97k_0_best_10-14.mp4`. Names never contain `*`. Because the
      name carries the range, re-running with the same ranges reuses the files already on disk.
- [ ] AC4: `download_sections` shows one `tqdm` bar counting sections
      (`desc="Downloading (sections)"`, `unit="section"`, `total=len(ranges)`), driven by the
      `finished` progress event — yt-dlp's ffmpeg downloader reports no byte progress, so the
      byte-based `_progress_hook` of video-download AC11 does not apply here.
- [ ] AC5: Any failure raises `RuntimeError` naming `source` and the requested ranges, chained
      (`from exc`) to the underlying error — same contract as `download` (video-download AC8).
- [ ] AC6: `pipeline.section_ranges(timestamps, window_seconds, pad, gap)` returns integer-second
      ranges that cover every timestamp's extraction window with `pad` on each side, clamped at 0,
      merged when they overlap or sit within `gap` of each other. Defaults:
      `SECTION_PAD_SECONDS = 0.5`, `SECTION_MERGE_GAP_SECONDS = 10.0`.
- [ ] AC7: For a URL source, a run that reaches the extraction stage fetches only those ranges.
      Each flagged timestamp's frames are read from the section containing it, with the section's
      start added back, so frame indices, timestamps, the `frame_<index>_<ts>s.jpg` names and every
      `timecodes.txt` line are the same as a full-download run of the same video.
- [ ] AC8: `pipeline.run(..., full_download=True)` and the CLI's `--full-download` restore the
      single best-quality download. A local-file source never attempts a section download, at
      either setting.
- [ ] AC9: When the merged ranges would cover more than `PARTIAL_MAX_COVERAGE` (0.5) of the scan
      video's duration, the run downloads the whole file instead and prints why. A video whose
      duration cannot be read skips the guard and goes partial.
- [ ] AC10: If `download_sections` raises, the reason is printed and the run falls back to a full
      download and completes. Turning this on by default cannot break a run that worked before.
- [ ] AC11: `src/extract_memes/socks_bridge.py` exposes `is_socks(proxy)` and
      `serve(socks_url)` — a context manager yielding `http://127.0.0.1:<port>` for a loopback
      HTTP proxy that tunnels through the SOCKS proxy using yt-dlp's bundled `yt_dlp.socks`
      (no new dependency). It answers `CONNECT host:port` only; any other method gets
      `501 Not Implemented` and an unreachable upstream gets `502 Bad Gateway`, so a request can
      never silently bypass the proxy. When `proxy` is a SOCKS URL, `download_sections` runs a
      bridge and passes it to ffmpeg alone as `-http_proxy` via
      `external_downloader_args={"ffmpeg_i": …}`; yt-dlp keeps the original SOCKS URL for its own
      requests.
- [ ] AC12: Offline tests (no network, yt-dlp mocked) cover: the yt-dlp options of AC2 and AC3
      including the `download_ranges` callable's output; the return value built from
      `requested_downloads`; `ValueError` on empty ranges; `RuntimeError` wrapping; `-http_proxy`
      present for a `socks5h://` proxy and absent for `http://` and for no proxy; the
      `section_ranges` merge table; partial used by default for a URL source; `full_download=True`
      and a local-file source both using `download`; the AC9 guard and the AC10 fallback; the
      bridge's CONNECT handshake against a stub SOCKS server, its 501 and its 502; and
      `--full-download` reaching `pipeline.run`.
- [ ] AC13: A `@pytest.mark.slow` test downloads two real ranges of `https://youtu.be/AElGyY97k_0`
      and asserts each section opens with `cv2.VideoCapture`, runs about as long as requested, and
      that its frame at `ts - section_start` matches the frame at `ts` from a full `best`
      download within a small mean-absolute-difference threshold.

## Out of Scope

- Stream-copied (non-re-encoded) sections. See Technical Notes for why the cut has to be exact.
- Parallel or resumed section downloads; sections are fetched one at a time, in order.
- Pruning old section files from `downloads/`. They accumulate exactly as full downloads do today.
- Making the scan (`worst`) pass partial. It has no timestamps to aim at yet.
- Proxy authentication beyond credentials already embedded in the proxy URL — see the backlog's
  "setup auth for the homeserver proxy".
- Non-YouTube sites, and YouTube videos with no video-only mp4 format: `download_sections` fails
  and AC10's fallback takes over.

## Technical Notes

- **Why ffmpeg cuts the sections.** yt-dlp routes any ranged download through `FFmpegFD`
  (`yt_dlp/downloader/__init__.py:89`), which places `-ss` before `-i` so the HTTP fetch starts at
  the section's byte offset. There is no native path for a plain https format.
- **Why the cut is re-encoded.** With `-c copy` the cut snaps back to the preceding keyframe and
  the file's absolute position is unrecoverable — `-t` runs from the keyframe, not from the
  requested start, so both ends shift by an unknown amount. `force_keyframes_at_cuts=True` makes
  yt-dlp drop `-c copy` (`yt_dlp/downloader/external.py:513`), and ffmpeg's accurate seek then
  discards decoded frames up to the requested start. CRF 12 is visually lossless for frames that
  are averaged together by `batch_cleaner` afterwards; the constant is one place to change.
- **Why the section selector is mp4-only.** The re-encoder follows the container: mp4 → libx264.
  A webm fallback would silently re-encode with libvpx-vp9, which is far too slow for this.
- **ffmpeg and SOCKS, measured** on this project's `static_ffmpeg` 7.0 binary: `-protocols` lists
  no `socks` and the binary contains no socks strings; `-http_proxy socks5h://…` and
  `HTTP_PROXY=socks5h://…` are both ignored and ffmpeg connects straight to the origin, while
  `-http_proxy http://…` is honored. `HTTP_PROXY` is what `FFmpegFD` sets from the `proxy` option
  (`yt_dlp/downloader/external.py:431-433`, warning about SOCKS two lines earlier). A silent
  bypass under the workflow's proxy would land the runner in the "Sign in to confirm you're not a
  bot" block of [ADR 017](../../decisions/017-macos-local-network-proxy-relay.md); hence AC11.
- **Why ranges are merged.** At the 2 fps scan rate one meme card flags several consecutive frames,
  and each additional section costs another fetch of the mp4 index plus a keyframe's worth of
  video. Merging nearby windows keeps section count — not window count — the thing that scales.
- No new runtime dependency: `yt_dlp.socks` ships with yt-dlp, and ffmpeg already arrives through
  `static-ffmpeg` ([ADR 006](../../decisions/006-youtube-video-only-formats-and-download-toolchain.md)).
- Decisions and the alternatives weighed:
  [ADR 019](../../decisions/019-partial-section-downloads.md).

## Open Questions

All resolved:

- Q1: Opt-in flag, or the default? **Default on** for URL sources, with `--full-download` as the
  escape hatch (user's call, 2026-09-19).
- Q2: What happens under a SOCKS proxy, which ffmpeg cannot use? **Ship a loopback HTTP-CONNECT
  bridge** so the partial path works everywhere the full path does (user's call, 2026-09-19).
  Falling back to a full download was rejected: both local runs and CI use SOCKS, so the feature
  would never engage.
- Q3: How are absolute timestamps preserved across a cut? **`force_keyframes_at_cuts=True`**, so
  the section starts exactly where it was asked to. Probing a stream-copied file's start time was
  rejected as unverifiable through OpenCV's timestamp handling.

## Changelog

- 2026-09-19: The user asked to plan and implement the backlog item "Fast partial high res video
  download. Only download fragments that include the meme timecodes." Wrote this spec and
  [ADR 019](../../decisions/019-partial-section-downloads.md) before any code, per the spec-driven
  workflow. Established by measurement, ahead of writing the ACs: yt-dlp sends every ranged
  download through `FFmpegFD`; a `-c copy` cut cannot be located in absolute time afterwards, so
  `force_keyframes_at_cuts=True` (a re-encode) is what makes `absolute = section_start + local`
  hold; and this project's bundled ffmpeg does not merely reject a SOCKS proxy but **silently
  ignores it** and connects direct, which is why AC11 exists. Resolved Q1 (default on) and Q2
  (ship the bridge) with the user. Status `ready`.
