---
title: "Fail When a Video Can't Be Decoded"
status: ready
created: 2026-10-05
updated: 2026-10-05
author: ""
depends-on: ["frame-extraction", "extraction-pipeline", "playlist-watch"]
---

# Fail When a Video Can't Be Decoded

## Problem Statement

When OpenCV can open a video but can't decode a single frame (the AV1 case on the GitHub runner,
see [decodable-codec-download](decodable-codec-download.md)), the pipeline treats it as an empty video. `sample_frames`
and `frames_from` stop quietly at the first failed read, so no frames are classified, no memes are
extracted, and `run` returns normally. The CLI exits 0, the workflow step passes, and the video is
marked processed, although nothing was saved or uploaded. A broken run is indistinguishable from a
video that genuinely has no memes.

## User Story

**Primary:**
As the maintainer, I want a run to fail when a video was downloaded but no frames could be read
from it, so that the workflow goes red, the video isn't marked processed, and I notice.

## Acceptance Criteria

- [ ] AC1: `sample_frames` raises `RuntimeError` naming the file when the video opens but its very
      first read fails (zero frames decoded). A read failing after at least one decoded frame is
      still the normal end of the video (frame-extraction AC3), with no error.
- [ ] AC2: In the extraction stage, if none of a meme's best-quality window frames could be
      decoded (`frames_from` yields nothing), `run` raises `RuntimeError` naming the file and the
      timestamp. A window whose frames decode but none of them is flagged is not an error, as before
      (extraction-pipeline AC17).
- [ ] AC3: The errors of AC1 and AC2 propagate like every other pipeline error: `pipeline.run`
      raises, the CLI exits non-zero with the message, and nothing is uploaded or sent. Files
      already written (for example `frames/`) stay.
- [ ] AC4: A video that decodes fine and has no flagged frames still prints `No memes found.` and
      returns `[]` with exit code 0. The same goes for a video that decodes, flags memes in the scan,
      but yields no saved images because no best-quality window frame is flagged.
- [ ] AC5: In the check-new-video workflow, the failure of AC3 fails the "Run the pipeline" step, so
      the "Mark the video as processed" and push steps (which have an implicit `success()`) don't run,
      and the workflow run is red. No workflow change is needed beyond that.
- [ ] AC6: Offline tests cover AC1–AC4 with mocked `cv2.VideoCapture`, with no network or `claude`.

## Out of Scope

- Making AV1 decode, or choosing codecs (see [decodable-codec-download](decodable-codec-download.md)).
- Retrying, or falling back to another format after a decode failure.
- The download step: `download` already raises `RuntimeError` when yt-dlp fails
  (video-download AC8), which propagates the same way.

## Technical Notes

- In the prod incident the scan copy (VP9) decoded and flagged memes; the best-quality copy (AV1)
  opened but yielded no frames, so every batch was empty and `run` returned `[]`.
- `cv2.VideoCapture.isOpened()` is true for an AV1 file even when its first read fails, which is why
  frame-extraction AC6 doesn't catch this.

## Open Questions

All resolved:

- Q1: A video that decodes, flags memes in the scan, but yields zero saved images? **Not an error**
  (AC4). That is a classifier result, not a decode failure.
- Q2: A video that decodes and flags nothing? **Success** (AC4), since some videos legitimately
  have no memes.
- Q3: Fail on the first undecodable meme window, or only when all fail? **On the very first**
  (AC2), so a partial result is never uploaded with memes silently missing.

## Changelog

- 2026-10-05: The user reported that the workflow succeeded in production without generating any
  data after the AV1 decode error, and asked it to fail when no video downloads or no frames parse.
  Traced it: `sample_frames`/`frames_from` return silently on a failed read, so `run` ends with
  `[]`. Drafted this spec. Not implemented; waiting for review of Q1–Q3.
- 2026-10-05: The user resolved all three questions: zero saved images from a decodable video is not
  an error (Q1), no flagged memes is success (Q2), and AC2 fails on the very first undecodable
  window (Q3). Extended AC4 to cover Q1; status `ready`. Not implemented yet.
