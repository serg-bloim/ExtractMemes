# 020 — Keep Downloading the Whole Video; Partial Fetching Is Not Viable

**Date:** 2026-09-19
**Status:** Accepted. Supersedes [019](019-partial-section-downloads.md).

## Context

[ADR 019](019-partial-section-downloads.md) decided that the best-quality pass should fetch only
the frame windows around flagged timestamps, and that shipped: yt-dlp section downloads with exact
cuts, merged ranges, a coverage guard, a fallback, `--full-download`, and a loopback SOCKS bridge,
with 258 tests passing (commit `a59df82`).

It was never timed. Bytes and correctness were measured; wall clock was assumed. When it was
finally timed, against a real 63-minute 1080p video using the 93 real meme timecodes from an
earlier run:

| approach | bytes over the wire | wall clock |
|---|---|---|
| whole-file download | 1.06 GB | **67.5 s** @ 15.7 MB/s, + 13.8 s decode |
| 70 ffmpeg-cut sections | — | ~700 s, + ~430 MB of re-encoded files |
| one stream + 93 seeks | 78 MB | 405 s |

Fetching 7% of the file took six times longer than fetching all of it.

The cause is not seeking, not the `n` challenge, and not the proxy. googlevideo **paces open-ended
range requests**: at one byte offset, `Range: bytes=N-` delivers 0.16 MB/s while a bounded
`bytes=N-N+10MB` delivers 25.6 MB/s — a ~164× difference. yt-dlp never asks open-ended
(`CHUNK_SIZE = 10 << 20`, `yt_dlp/extractor/youtube/_video.py:3229`), which is the only reason the
whole-file download is fast. **ffmpeg always asks open-ended**, and has no per-request bound —
`-end_offset` is one static absolute offset, not a chunk size. Every design that routes the media
fetch through ffmpeg therefore runs at 0.16 MB/s.

The full evidence, including the HLS/progressive split, the EJS-solver dead end and the section-cut
mechanics, is in [the spec](../specs/features/partial-high-res-download.md).

## Decision

1. **The best-quality pass downloads the whole file, as it did before ADR 019.** `downloader.download`
   is unchanged and remains the only download path.
2. ADR 019's implementation is **reverted**: `download_sections`, the section plumbing in
   `pipeline.run`, `--full-download`, `socks_bridge.py` and their tests are removed. They remain in
   git history at `a59df82` for anyone who returns to this.
3. The spec is marked `deprecated` and rewritten as a **research record** rather than deleted. The
   measurements cost more than the code did, and the next person to have this idea should meet the
   evidence before writing anything.
4. Any future attempt must have **Python, not ffmpeg, do the network reading**, in bounded ≤10 MB
   requests, and must **prototype the timestamp→byte-range mapping before anything else** — that is
   the one unmeasured piece left. See the spec's Q3.

## Options Considered

- **A. Keep the shipped section downloader.** Rejected: ~700 s against 67.5 s, plus ~430 MB of
  re-encoded files and a per-section failure mode.
- **B. Replace sections with one open stream and repeated seeks.** Genuinely better than A — 78 MB
  instead of 430 MB, no re-encode, no cut-accuracy problem, 0.3 MB index read, seeks landing within
  a frame — and still 405 s against 67.5 s, because ffmpeg does the reading. Rejected.
- **C. Keep partial anyway, for bandwidth rather than time.** 78 MB against 1.06 GB is a real win if
  the proxy link is ever the binding constraint. Rejected for now: it is 6× slower today, and
  nobody is metering that link. Reconsider only alongside decision 4.
- **D. Build the Python-side bounded-range fetch into a sparse file.** The design the evidence
  actually points to, and plausibly 4× faster than the status quo *and* 13× lighter. Not started:
  it needs an mp4 sample-table parser, and two designs have already died on an unmeasured
  assumption. Left as the spec's open question rather than begun on a third guess.

## Consequences

- The pipeline is exactly what it was before this work: simple, and fast for the reason we now
  understand rather than by luck.
- Roughly 1100 lines of code and tests are deleted. That is the cost of having measured the wrong
  thing — bytes, twice — before measuring the clock.
- Two findings outlive the feature and are worth carrying forward:
  - **ffmpeg silently ignores SOCKS proxies** (measured; it connects direct rather than failing).
    Any future use of ffmpeg for networking needs the loopback CONNECT bridge from `a59df82`, or it
    will quietly leave the proxy. Nothing in the pipeline does ffmpeg networking today.
  - **googlevideo's pacing rule** explains download throughput generally, not just here. If a
    whole-file download is ever slow, check whether something is issuing open-ended range requests.
- `specs/BACKLOG.md` loses "Fast partial high res video download"; it is answered, not pending.

## References

- [specs/features/partial-high-res-download.md](../specs/features/partial-high-res-download.md) —
  the measurements, in full
- [ADR 019 — Download Only the Meme Windows](019-partial-section-downloads.md) — superseded
- [specs/features/video-download.md](../specs/features/video-download.md)
- [ADR 006 — YouTube Downloads: Video-Only Formats, Node.js JS Runtime, Bundled ffmpeg](006-youtube-video-only-formats-and-download-toolchain.md)
- [ADR 017 — Reaching a LAN Proxy from Python Under macOS Local Network Privacy](017-macos-local-network-proxy-relay.md)