# 019 — Download Only the Meme Windows, Cut by ffmpeg, Through a Loopback SOCKS Bridge

**Date:** 2026-09-19
**Status:** Accepted

## Context

The pipeline downloads the source twice in full: once at `worst` to scan for memes, once at `best`
to read a ±1s batch of frames around each flagged timestamp. The second download is almost entirely
waste — the frames actually read are a small fraction of the file, and their timestamps are already
known when it starts. On a long video that is hundreds of megabytes, and in the scheduled workflow
every byte crosses a home SOCKS proxy, which is the slowest and least reliable link in the run.
`specs/BACKLOG.md` has carried "Fast partial high res video download" since the backlog was
created.

Three things constrain the shape of a fix:

1. yt-dlp routes **any** ranged download through its ffmpeg downloader
   (`yt_dlp/downloader/__init__.py:89`). There is no native byte-range path for a plain https
   YouTube format.
2. A stream-copied (`-c copy`) cut starts at the keyframe preceding the requested time, and `-t`
   then runs from that keyframe, so both ends shift by an unknown amount. The pipeline needs
   absolute timestamps — `timecodes.txt` and the `frame_<index>_<ts>s.jpg` names depend on them.
3. ffmpeg has no SOCKS support. Measured on this project's `static_ffmpeg` 7.0 binary:
   `-protocols` lists no `socks`, the binary contains no socks strings, and both
   `-http_proxy socks5h://…` and `HTTP_PROXY=socks5h://…` are **silently ignored** — ffmpeg
   connects straight to the origin. `HTTP_PROXY` is exactly what yt-dlp's `FFmpegFD` sets from the
   `proxy` option (`yt_dlp/downloader/external.py:431-433`), which warns about it two lines
   earlier. `-http_proxy http://127.0.0.1:9` *is* honored.

Point 3 is the dangerous one: the failure is not an error but a bypass, which would send direct
requests from the GitHub runner into the "Sign in to confirm you're not a bot" block that
[ADR 017](017-macos-local-network-proxy-relay.md) ends on.

A fourth constraint surfaced only once this ran against YouTube: the format the existing
`bv*[ext=mp4]/bv*` selector picks is usually an HLS playlist (`m3u8_native`), and seeking into one
is not a ranged fetch. Asking for two 3-second sections of the 12-second test video that way
produced one 391 KB file out of a 433 KB video and one 261-byte file with no frames in it.

## Decision

1. The best-quality pass fetches **only the frame windows around flagged timestamps**, via yt-dlp's
   `download_ranges`. This is the **default** for URL sources; `--full-download` restores the old
   behavior, and local-file sources are untouched.
2. Sections are cut with `force_keyframes_at_cuts=True`, which makes yt-dlp drop `-c copy`
   (`yt_dlp/downloader/external.py:513`) so ffmpeg's accurate seek starts the file exactly at the
   requested second. The resulting re-encode is pinned to `-c:v libx264 -crf 18 -preset veryfast`.
   The section selector is `bv*[ext=mp4][protocol=https]`: `mp4` so the container — and therefore
   the encoder — is predictable, and `https` because a range is only a range against a
   progressive stream. Ranging an HLS playlist, which is what YouTube's best format usually is,
   fetched nearly the whole video for one section and produced an empty file for another.
3. Windows are merged into as few integer-second ranges as possible (overlapping, or within 10s).
   If the merged ranges would still cover more than half the video, the run downloads the whole
   file instead; if a section download fails, the run says why and falls back to a full download.
4. When the proxy is a SOCKS URL, a loopback **HTTP-CONNECT bridge** (`socks_bridge.py`, built on
   yt-dlp's bundled `yt_dlp.socks`) is started for the duration of the download and handed to
   ffmpeg as `-http_proxy`. yt-dlp keeps the original SOCKS URL for its own requests. The bridge
   answers `CONNECT` only — anything else is refused — so nothing can quietly leave the proxy.

## Options Considered

- **A. Keep downloading the whole file.** The status quo. Simple and correct, but the backlog item
  exists precisely because it is slow over the proxy.
- **B. Stream-copy the sections and recover the offset afterwards** (`-copyts`, or probing the
  cut file's container start time). No re-encode, but recovering the absolute offset depends on
  how ffmpeg's mp4 muxer writes timestamps *and* on how OpenCV reports them — two behaviors that
  could not be established without trying it, against a correctness requirement
  (`timecodes.txt`) where being quietly wrong is worse than being slower. Rejected.
- **C. Resolve the format URL and drive ffmpeg directly**, emitting PNG frames instead of video
  sections. Exact and lossless, but it re-implements what yt-dlp already does around format
  selection, signatures, headers and PO tokens — the part of this stack that breaks most often.
  Rejected as the larger long-term liability.
- **D. Fall back to a full download whenever the proxy is SOCKS.** Two lines of code, but both
  local runs and the scheduled workflow use SOCKS, so the feature would never actually run.
  Rejected.
- **E. Pass the proxy through to ffmpeg and let it fail.** Rejected outright: it does not fail, it
  bypasses (see Context 3).

## Consequences

- The second download shrinks to the merged windows plus a keyframe's lead-in per section. The
  saving scales with how sparse the memes are; dense videos hit the coverage guard and behave as
  before.
- Section files accumulate in `downloads/` as `<id>_best_<start>-<end>.mp4`, named by range so
  re-runs reuse them. They are re-encoded, so they are not byte-identical to the source; measured,
  CRF 18 sits 1.6/255 from CRF 12 at half the size, well inside what the JPEG write and
  `batch_cleaner`'s averaging do afterwards. `SECTION_ENCODE_ARGS` is the single place to revisit.
- **Partial runs read a different stream than whole-file runs.** Requiring `protocol=https` means
  the section selector lands on a different codec than `bv*[ext=mp4]/bv*` — measured, 1080p AV1
  against 1080p VP9, and 360p H.264 against 360p VP9 — at the same resolution. Which memes are
  found, and their frame names and timecodes, are identical; the pixels are a few levels of grey
  apart. If YouTube ever stops offering a progressive mp4, sections fail and decision 3's fallback
  takes over.
- CPU cost moves from the network to the local encoder — a few seconds of video per meme.
- The partial path is YouTube-mp4-shaped. Anything else raises, and decision 3's fallback covers it.
- A new module with a socket server in it, `socks_bridge.py`, is now part of the package. It binds
  loopback on an ephemeral port, lives only for the duration of a download, and speaks one verb.
- ffmpeg becomes load-bearing for extraction, not just for remuxing. It already ships via
  `static-ffmpeg` ([ADR 006](006-youtube-video-only-formats-and-download-toolchain.md)), and
  Option D of that ADR — "accept MPEG-TS bytes in a `.mp4`" — is no longer a viable escape hatch
  for the extraction pass.

## References

- [specs/features/partial-high-res-download.md](../specs/features/partial-high-res-download.md)
- [specs/features/video-download.md](../specs/features/video-download.md)
- [ADR 006 — YouTube Downloads: Video-Only Formats, Node.js JS Runtime, Bundled ffmpeg](006-youtube-video-only-formats-and-download-toolchain.md)
- [ADR 017 — Reaching a LAN Proxy from Python Under macOS Local Network Privacy](017-macos-local-network-proxy-relay.md)
