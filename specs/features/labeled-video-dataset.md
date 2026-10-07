---
title: "Labeled Video Dataset"
status: draft
created: 2026-10-07
updated: 2026-10-07
author: ""
depends-on: ["video-download", "frame-extraction", "decodable-codec-download"]
---

# Labeled Video Dataset

## Problem Statement

The heuristic classifier (ADR 008) was calibrated on 38 hand-picked 256x144 PNGs and later checked by
eye on whole videos, which found frames it wrongly flags (a presenter in front of a striped wall,
a blurred-side vertical video). Trying better criteria needs a larger, repeatable test set, but
storing thousands of frames in the repo is heavy. The set should be just a reference to a video file
plus the frames a human marked, so the frames can be re-created whenever they are needed.

This is development tooling: it lives outside the installable package and is not part of the
production image or the GitHub Actions install.

## User Story

**Primary:**
As the developer improving the classifier, I want a YAML file per video that identifies the exact
video file and lists the memes I marked, so that I can reload the labeled frames at any time without
keeping images on disk.

## Acceptance Criteria

- [ ] AC1: A dataset lives in `data/datasets/<video-id>.yaml`, one file per video, committed to the
      repo. It is human-readable and diff-friendly.
- [ ] AC2: The file records the video identity: the source URL, the video id, and the yt-dlp
      `format_id` that was labeled, plus `vcodec`, container `ext`, `width`, `height`, native
      `fps` and total `frame_count` as they were when labeled.
- [ ] AC3: The file has a `schema` version and a `mode` (`standard` or `precise`), and a `memes`
      list. Each meme is a YAML mapping of attributes, so more can be added later without changing
      the shape:
      - standard mode: `meme_ts` (seconds) and `meme_frame` (frame index) — one moment, any frame
        while the meme is on screen;
      - precise mode: `meme_start_ts`, `meme_start_frame`, `meme_end_ts`, `meme_end_frame` — the
        first and last frame of the meme.
      Memes are sorted by frame and a frame appears in at most one meme. Only the standard mode is
      implemented now; the loader rejects `precise` files with a clear "not supported yet" error.
- [ ] AC4: A frame's index is its 0-based position in sequential decoding of the file, and its
      timestamp is that frame's own presentation time (`CAP_PROP_POS_MSEC`), exactly as
      `frame_extractor.sample_frames` reports them — never `frame_index / native_fps`, which drifts
      on files with uneven frame spacing. `meme_ts` is written with 3 decimals.
- [ ] AC5: A loader reads a dataset and returns the video's local path, downloading that exact
      `format_id` (not a "worst/best" selector) into `.runtime/downloads/` if it isn't there yet.
      A local file that is already present is reused.
- [ ] AC6: After obtaining the video, the loader compares the file's `width`, `height`, `fps` and
      `frame_count` with the recorded ones and raises a clear error naming the differing field if
      any differ. It never silently labels a different encode.
- [ ] AC7: The loader finds each meme's frame by `meme_frame` using sequential decoding, and checks
      that the decoded frame's timestamp equals `meme_ts` (to the millisecond), raising on a
      mismatch. It doesn't rely on seeking to find a frame.
- [ ] AC8: The loader can yield the positive frames (BGR arrays with index and timestamp) and the
      negative frames. Negatives are the frames sampled at a given fps that lie outside an
      exclusion window of ±1.0 s (overridable) around every positive timestamp, because a meme lasts
      several frames and only one of them is marked in standard mode.
- [ ] AC9: Offline tests cover reading and writing a dataset file, the validation in AC6/AC7, and the
      positive/negative split in AC8, using a small synthetic video. No test touches the network.
- [ ] AC10: Nothing in `src/extract_memes/` imports this code, and its dependency (PyYAML) is not in
      `[project.dependencies]`: it goes in a separate optional group (e.g. `labeling`), so
      `pip install .` and `pip install -e .` as used by the Dockerfile and the GitHub workflow don't
      pull it in.

## Out of Scope

- The labeling UI (see [frame-labeler](frame-labeler.md)).
- Running and comparing candidate criteria over a dataset (a later spec).
- Precise mode itself (labeling every frame between a start and an end) — only reserved in AC3.
- Migrating `data/labeled_dataset/` into this format; it stays as is (ADR 008).
- Datasets for local video files, which have no URL to re-fetch.

## Technical Notes

- Suggested layout: `tools/labeling/dataset.py`, tests under `tests/` that `importorskip("yaml")` so
  the offline suite still passes without the labeling extra. It reuses `downloader` and
  `frame_extractor` from the package. `tools/` is already outside the package (`src/` layout), so it
  isn't built into the image.
- Downloading by `format_id` needs the downloader to accept a format selector other than the two
  tiers; whether that's a new parameter on `download` or a separate call in the tool is for the
  implementation to decide, but production behavior of `download` must not change.
- The yt-dlp format ids for a video are only stable while YouTube keeps serving them. AC6 is what
  catches a format that disappeared or was re-encoded.
- Sequential decoding of a long low-quality video takes a while (minutes for an hour of 144p). That
  is the price of exact indices and timestamps (AC4, AC7); a cached index is the labeler's concern.
- A meme card lasts ~10 frames at 25 fps (ADR 008), so ±1 s clears it. Precise mode will remove
  the need for the exclusion window.
- Example:

  ```yaml
  schema: 1
  mode: standard
  video:
    url: https://www.youtube.com/watch?v=FtU4MuksCzE
    id: FtU4MuksCzE
    format_id: "160"
    vcodec: avc1.4d400c
    ext: mp4
    width: 256
    height: 144
    fps: 25.0
    frame_count: 94540
  memes:
    - {meme_ts: 163.240, meme_frame: 4081}
  ```

## Open Questions

Resolved by the user (2026-10-07):

- Q1: Frame index alongside the timestamp? **Yes, as separate per-meme attributes** (`meme_ts`,
  `meme_frame`; `meme_start_*` for precise mode) — AC3.
- Q2: ±1.0 s exclusion window? **Yes** — AC8.
- Where the code lives: **dev tooling, not prod code** — AC10.
- Timestamps: **taken from the frame itself**, as the scan does now — AC4.

## Changelog

- 2026-10-07: The user asked for a classifier-criteria subproject: a dataset that stores only a
  video reference (URL plus codec info) and marked frames, in `data/datasets/<video-id>.yaml`,
  with standard mode (one timestamp per meme) first and precision mode later. Drafted this spec and
  [frame-labeler](frame-labeler.md).
- 2026-10-07: The user answered the open questions: per-meme attributes (`meme_ts`, `meme_frame`;
  `meme_start_*` for precise), ±1 s window, dev tooling excluded from the production install, exact
  frame-derived timestamps. Spec updated. Status `draft`, awaiting the user's go-ahead.
