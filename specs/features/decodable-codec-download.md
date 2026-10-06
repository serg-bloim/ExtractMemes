---
title: "Download a Codec OpenCV Can Decode"
status: ready
created: 2026-10-05
updated: 2026-10-05
author: ""
depends-on: ["video-download"]
---

# Download a Codec OpenCV Can Decode

## Problem Statement

The `worst` and `best` selectors (video-download AC3) choose a format by quality only, so yt-dlp
may hand back an AV1 file. OpenCV's bundled FFmpeg decodes AV1 only with hardware acceleration, so
on a machine without it (the GitHub Actions runner) it prints "Your platform doesn't support
hardware accelerated AV1 decoding" / "Failed to get pixel format" and yields no frames. This
happened on `FtU4MuksCzE`, where `best` resolves to AV1 1080p (format 399); on the developer's Mac the
same file decodes fine, so the failure only shows up elsewhere. The run then produces no memes.

## User Story

**Primary:**
As the user, I want the downloaded copies to use a codec the pipeline can always decode, so that a
run produces the same frames on a laptop and on a CI runner.

## Acceptance Criteria

- [ ] AC1: For a URL source, neither `worst` nor `best` resolves to an AV1 (`av01`) format when
      the video offers any other video format.
- [ ] AC2: Within that restriction, `worst` is still the lowest-quality and `best` the
      highest-quality format, and a video-only format is still enough (no audio, nothing merged),
      as in video-download AC3.
- [ ] AC3: If AV1 is the only video format offered, it is downloaded and the run carries on to try
      to decode it, with no new failure or warning at the download step.
- [ ] AC4: The offline downloader tests assert the selector for both `worst` and `best` and that
      each excludes AV1 with a fallback that allows it (AC1, AC3); no network.
- [ ] AC5: A `slow` test downloads the permanent test video at both qualities and checks that
      the codec of the saved file is not AV1.

## Out of Scope

- Decoding AV1 (installing dav1d, building OpenCV with it) or re-encoding downloaded files.
- Preferring one specific codec (H.264 vs VP9) beyond excluding AV1.
- Changing file naming, the partial-download behaviour, or the playground.

## Technical Notes

- Sizes for `lx011zFYIGU` at 1080p: AV1 272 MiB, VP9 359 MiB, H.264 498 MiB. Excluding AV1 makes
  the best-quality download larger.
- Measured 2026-10-05 for `FtU4MuksCzE`: `worst` → 602 (VP9, 256x144), `best` → 399 (AV1, 1080p).
  For `lx011zFYIGU` both already resolve to VP9. The scan copy was never the problem.
- A selector shaped like `bv*[vcodec!^=av01]/bv*` would satisfy AC1 and AC3 (the second branch is
  the AV1 fallback), but the existing `[ext=mp4]` preference must be kept compatible with it.
  Confirm the exact selector against yt-dlp before implementing.
- `playground/ytdlp_playground.py` lists a video's formats.

## Open Questions

All resolved:

- Q1: Exclude only AV1, or force H.264? **Exclude only AV1** (AC1). Files stay smaller, and yt-dlp
  still ranks the remaining codecs.
- Q2: What if AV1 is the only video format offered? **Download it anyway and try to parse it**
  (AC3), in case the machine can decode it. No warning and no early failure.

## Changelog

- 2026-10-05: The user reported the AV1 decoder error on `FtU4MuksCzE` in a GitHub Action. Checked
  the selectors with yt-dlp: `best` resolves to AV1 there, and the local copy decodes fine on macOS.
  Drafted this spec. Not implemented; waiting for review of Q1 and Q2.
- 2026-10-05: The user resolved both questions: only AV1 is excluded (Q1), and when nothing else is
  offered the AV1 copy is still downloaded and parsed, in case it decodes (Q2). Updated AC3 and
  the Open Questions, status `ready`. Not implemented yet, at the user's request.
