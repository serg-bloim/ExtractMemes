---
title: "Partial High-Res Download"
status: deprecated
created: 2026-09-19
updated: 2026-09-19
author: ""
depends-on: ["video-download", "extraction-pipeline"]
---

# Partial High-Res Download

> **Not implemented — do not build this.** Two working designs were built and measured against a
> real video; both were several times *slower* than downloading the whole file. The code was
> reverted. This spec is kept as the research record: everything below is measured, so a future
> attempt starts from evidence instead of repeating it. The one condition that would make it worth
> revisiting is in [Open Questions](#open-questions).

## Problem Statement

The extraction stage downloads the whole source video a second time at best quality, then reads
only a ±`window_seconds` batch of frames around each flagged timestamp. On a 20-minute 1080p
compilation that is hundreds of megabytes fetched to decode a few seconds per meme, and in the
scheduled workflow every one of those bytes crosses a home SOCKS proxy. The frames the pipeline
actually reads are a small, known fraction of the file, and they are known before the download
starts — the scan pass has already produced the timestamps.

The premise is sound. It is the *transport* that does not cooperate — see Findings.

## User Story

**Primary:**
As someone running the pipeline on a long video, I want the best-quality pass to fetch only the
moments that contain memes, so that a run finishes in a fraction of the bandwidth and time.

## Outcome

Measured on `https://youtu.be/0TSqnhLXYfA` — 63 minutes (3763.8 s), 1080p — using the **93 real
meme timecodes** from a previous run (`.runtime/0TSqnhLXYfA/timecodes.txt`), with
`window_seconds=1.0` (51 frames per meme, 4743 frames total):

| approach | bytes over the wire | wall clock |
|---|---|---|
| **whole-file download (what the pipeline does)** | 1.06 GB | **67.5 s** @ 15.7 MB/s, + 13.8 s to decode all 4743 frames |
| 70 ffmpeg-cut sections (`yt-dlp --download-sections`) | — | ~700 s (~10 s per section), plus ~430 MB of re-encoded files |
| one stream opened once + 93 seeks (OpenCV) | **78 MB** | **405 s** |

Fetching 7% of the file took 6× longer than fetching all of it. The feature cannot pay for itself
while that holds.

## Findings

### 1. The root cause: googlevideo paces open-ended range requests

All probes below hit the *same* byte offset of the same progressive URL (itag 399), back to back:

| request | throughput |
|---|---|
| `Range: bytes=N-` (open-ended), read 1 MB and stop | **0.16 MB/s** — 6.1 s for one megabyte |
| `Range: bytes=N-N+1MB` (bounded) | 8.4 MB/s |
| `Range:` bounded 10 MB | 25.6 MB/s |
| `Range:` bounded 11 MB | 26.7 MB/s |
| `Range:` bounded 20 MB | 0.17 MB/s |

A **bounded** request of roughly ≤10 MB is served at full speed; an **open-ended** one — or a very
large one — is paced to ~0.17 MB/s from the first byte. That is a ~164× difference and it is the
single fact that decides this feature.

yt-dlp knows: `CHUNK_SIZE = 10 << 20` in `yt_dlp/extractor/youtube/_video.py:3229`, used to split
progressive formats into 10 MB chunk requests. That, and nothing else, is why the pipeline's
whole-file download reaches 15.7 MB/s.

### 2. ffmpeg always asks open-ended, and cannot be told not to

ffmpeg's `http` protocol issues `Range: bytes=N-` and streams. So *every* design that lets ffmpeg
do the network reading is pinned at 0.16 MB/s: yt-dlp's section downloader, OpenCV seeking on a
URL, and `ffprobe`. There is no per-request bound available — `-end_offset` is a single **static
absolute** offset ("try to limit the request to bytes preceding this offset"), not a chunk size,
so it cannot express "cap each request at 10 MB" for a workload that seeks all over the file.

### 3. The fast path is not seekable; the seekable path is not fast

- `bv*[ext=mp4]/bv*` — what the pipeline already uses — resolves to **HLS** (itag 616,
  `m3u8_native`). It runs at 15.7 MB/s. Seeking it through OpenCV pulled **665 MB in 31 s and
  decoded zero frames**.
- The only rangeable format is progressive `https` (itag 399, AV1 1080p, 316 MB). OpenCV opens it
  in 1.8 s reading only **0.3 MB** of index, and seeks land within one frame of the target —
  but every read is paced per finding 1.

Same resolution either way (1080p vs 1080p; on another video 360p vs 360p), different codec.

### 4. The `n` challenge was a red herring

Every run warns `n challenge solving failed` and recommends `--remote-components ejs:github`.
Enabling it changed nothing: **0.17 MB/s with the EJS solver, 0.17 MB/s without.** The itag 399
URL carries no `n` parameter at all. (The earlier belief that it did came from a bad substring
test — `'n=' in url` matches `cle**n=**316176273`.)

### 5. ffmpeg silently ignores a SOCKS proxy

Measured on this project's bundled `static_ffmpeg` 7.0 binary: `-protocols` lists no `socks` and
the binary contains no socks strings; `-http_proxy socks5h://…` **and** `HTTP_PROXY=socks5h://…`
are both ignored and ffmpeg connects **straight to the origin**, while `-http_proxy http://…` is
honoured. `HTTP_PROXY` is exactly what yt-dlp's `FFmpegFD` sets from the `proxy` option
(`yt_dlp/downloader/external.py:431-433`, which warns about it two lines earlier).

This matters beyond this spec: **any** future use of ffmpeg for networking needs a loopback
HTTP-CONNECT bridge, or it will quietly leave the proxy. A working one (built on yt-dlp's bundled
`yt_dlp.socks`, CONNECT-only so nothing can fall through to a direct connection) exists in the
reverted commit.

### 6. Mechanics of ffmpeg-cut sections, if anyone returns to that route

- A `-c copy` cut snaps back to the preceding keyframe, and `-t` then runs from *that* keyframe, so
  both ends shift by an unknown amount and the section's absolute position is unrecoverable.
  `force_keyframes_at_cuts=True` makes yt-dlp drop `-c copy`
  (`yt_dlp/downloader/external.py:513`); ffmpeg's accurate seek then starts the file exactly at the
  requested second, at the cost of a re-encode.
- The section selector must exclude HLS. Ranging an `m3u8` playlist produced one 391 KB file out of
  a 433 KB video and one **261-byte file with zero frames**.
- Re-encode cost on a 3 s section: crf 12 → 550 KiB, crf 18 → 268 KiB, crf 23 → 152 KiB, with crf
  18 a mean absolute difference of only 1.6/255 from crf 12. On 1080p AV1 source, crf 18 still
  inflated ~10× over the source bitrate (~430 MB of sections for 13.5% of a 316 MB video).
- `%(section_start)d` works in a yt-dlp output template even though the value is a float, giving
  content-addressed names like `AElGyY97k_0_best_10-14.mp4`.

### 7. Things that turned out cheaper or dearer than assumed

- The mp4 index read is **0.3 MB**, not the several MB assumed when merging ranges was justified.
- Decoding all 4743 frames from a local file takes **13.8 s** — negligible next to any download.
- `ffprobe -show_entries packet=pts_time,pos,size` against the remote URL, to build a
  timestamp→byte map, **never finished**: killed after 600 s, streaming the file at paced speed.
- Section downloads hit one transient `ffmpeg exited with code 8` that succeeded on retry — over
  70 sequential requests, a whole-batch abort is a real exposure.

## Acceptance Criteria

**None — this is not to be implemented.** A complete implementation with 258 passing tests
(offline + network) exists in commit `a59df82`, reverted by the commit that deprecated this spec.
It covered `downloader.download_sections`, merged section ranges, a coverage guard, an error
fallback, `--full-download`, and the SOCKS bridge of finding 5. Recover it from git history rather
than rewriting it, should finding 1 ever stop being true.

## Out of Scope

- Everything. See the Outcome table.

## Open Questions

- Q1: Opt-in flag, or the default? **Resolved then void** — it shipped as the default with
  `--full-download` to opt out, and was reverted wholesale.
- Q2: What happens under a SOCKS proxy, which ffmpeg cannot use? **Resolved:** a loopback
  HTTP-CONNECT bridge, built and tested (finding 5). Void with the feature, but the finding stands
  for any future ffmpeg networking.
- Q3: **Still open — the only route worth revisiting.** Findings 1 and 2 together say a partial
  fetch can only be fast if **Python, not ffmpeg, does the network reading**, in bounded ≤10 MB
  range requests through yt-dlp's own networking (which also makes SOCKS work natively and retires
  the bridge). The sketch: fetch only the needed byte ranges, write them into a **sparse** local
  file at their true offsets — disk then costs only what was fetched — and decode it with
  `frames_from` unchanged. Estimated at ~78 MB in ~4 s plus 13.8 s of decode, against 67.5 s + 13.8 s
  today.
  The unsolved piece is mapping timestamp → byte range, which needs the mp4 sample tables
  (`stts`/`stss`/`stsc`/`stsz`/`stco`). `ffprobe` cannot supply it over the network (finding 7), so
  it means either parsing `moov` in Python or materialising `moov` into the sparse file and probing
  that locally. Nobody has measured whether that holds up. **Do not start it without prototyping
  the index mapping first** — two designs already died on an unmeasured assumption.

## Changelog

- 2026-09-19: The user asked to plan and implement the backlog item "Fast partial high res video
  download. Only download fragments that include the meme timecodes." Wrote this spec and
  [ADR 019](../../decisions/019-partial-section-downloads.md) before any code, per the spec-driven
  workflow. Resolved Q1 (default on) and Q2 (ship the bridge) with the user. Status `ready`.
- 2026-09-19: Implemented as yt-dlp section downloads with exact cuts and a SOCKS bridge; 258 tests
  passing, and a real end-to-end run producing identical frame names and timecodes to a whole-file
  run. Committed as `a59df82`. Status `implemented`.
- 2026-09-19: The user asked whether partial downloading had actually been *timed*. It had not —
  only bytes and correctness were measured. Timing it on a real 63-minute video with 93 real memes
  produced the Outcome table: both partial designs are several times slower than the whole-file
  download. Chasing the cause produced findings 1–7, including the discovery that the `n` challenge
  and the EJS solver were irrelevant and that googlevideo's pacing of open-ended range requests is
  the real constraint. The user called the feature infeasible and asked to keep the research.
  Reverted `a59df82`'s code, tests, `--full-download` and `socks_bridge.py`; rewrote this spec as
  the record; wrote [ADR 020](../../decisions/020-whole-video-download-stands.md) superseding
  ADR 019. `pytest -m "not slow"` back to 204 passing on the restored code. Status `deprecated`.