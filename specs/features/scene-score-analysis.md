---
title: "Scene Score Analysis and Claude Verification"
status: in-progress
created: 2026-10-08
updated: 2026-10-08
author: ""
depends-on: ["frame-labeler", "classifier-criteria", "heuristic-classifier", "criteria-evaluation"]
---

# Scene Score Analysis and Claude Verification

## Problem Statement

The production rule (`band > 180`) is tuned on a few hand-labeled videos. On an unlabeled video there
is no ground truth, so there is no way to tell whether it misses memes (scores just under the
threshold) or flags non-memes (scores just over it, or mixed within one shot). Looking at every
frame is impractical; looking only at the scenes whose scores sit near the threshold or disagree
with themselves is cheap, and Claude can judge those few images.

The work is split in parts. **Part 1 (this spec's implemented scope): a scene database** holding
per-scene score statistics for every analyzed video and criterion, and Claude's verdict per scene,
behind a small API so nothing edits the file by hand. **Part 2 (later, not yet specified in detail):**
the selection of borderline scenes and the Claude verification runs (phase 1 misses, phase 2 false
positives), which read and write the database only through that API.

## User Story

**Primary:**
As the developer tuning the classifier, I want per-scene score statistics for unlabeled videos kept
in one database, and Claude's verdict on borderline scenes stored next to them, so that I can find
missed memes and false positives without labeling the videos by hand.

## Terminology

- **Scene**: a labeler *row* — a run of consecutive similar frames (`tools/labeling/index.py`,
  `similarity.py`). Frames are the video's own decoded frames, as in the labeler cache.
- **Frame locator**: `(video_id, format_id, frame_index)`. It identifies the scene whose
  `first_frame..last_frame` contains the frame. A scene's own key is `(video_id, format_id, first frame)`.
- **Criterion stats**: for one criterion and its condition (`op`, `threshold`, default the production
  rule's, `band > 180`), the scene's score `min`, `max`, `mean`, `std` and `share_flagged` (fraction of
  frames for which the condition holds).

## Acceptance Criteria

### Part 1a — Scene database

- [x] AC1: One YAML file, `data/datasets/scene_analysis/scene_analysis.yaml` (gitignored with
      `data/datasets/`), holds all videos and criteria as a tree: `version: 2`, then `videos` (each
      `video_id` and `formats`), each format (`format_id` and `scenes`), each scene in ascending frame
      order with `first_frame` (its key within the format), `last_frame`, `start_ts`,
      `end_ts`, `frame_count`, `stats` (a map criterion name → `op`, `threshold`, `min`, `max`, `mean`,
      `std`, `share_flagged`; the first, second and last null without a condition) and `claude` (null
      until checked). Scenes of one format never overlap.
- [x] AC2: All access goes through the Python API `tools/scene_analysis/store.py` (`SceneStore`);
      no other code reads or writes the file. **Every operation returns a `Response(status, message,
      data)` with an HTTP-style status** instead of raising: 200 done (something changed, or a read),
      201 created, 204 valid but nothing changed (no write happens), 400 invalid argument, 404 no such
      scene, 409 conflict, 500 the file is unreadable or off-schema. `Response.ok` is true for 2xx.
      The operations:
      - `insert_scene(video_id, format_id, first_frame, last_frame, start_ts, end_ts, frame_count, stats)`:
        201; 409 if a scene already starts at `first_frame` or the new one overlaps another; 400.
      - `set_criterion_stats(video_id, format_id, first_frame, criterion, stats)`: 201 criterion new on the
        scene, 200 replaced, 204 already exactly these stats, 404, 400.
      - `get_scene(video_id, format_id, first_frame)` and `find_scene(video_id, format_id, frame_index)`
        (by frame locator): 200 with the scene as `data` (flat, with `video_id` and `format_id` added), 404.
      - `select_scenes(predicate)`: 200 with the matching scenes as `data`.
      - `set_claude_status(video_id, format_id, frame_index, verdict, reason, check)` by frame locator
        (`verdict`: `meme` | `not_meme` | `unsure`; `check`: `miss` | `false_positive`): 201 first status,
        200 replaced by a different one, 204 same verdict/reason/check (`checked_at` kept), 404, 400.
- [x] AC3: Corruption safety: every write is atomic (written to a temp file in the same directory,
      flushed to disk, then renamed over the file), the previous version is kept as
      `scene_analysis.yaml.bak`, concurrent writers are serialized with a lock file, and a file that
      does not parse or does not match the schema makes every operation return 500 without writing
      anything. `with store.batch():` applies many operations with one read and one write and writes
      nothing if the block raises (it raises `SceneStoreError` itself if the file can't be read; I/O errors
      such as a full disk propagate).
- [x] AC4: Values are stored as plain YAML numbers/strings (numpy types converted), and a stored
      scene round-trips unchanged.

### Part 1b — Population

- [x] AC5: `python -m tools.scene_analysis populate <video-id-or-url> [--format-id ID] [--proxy URL] [--db FILE]`
      takes the video as the labeler does: a video with a dataset is pinned to the dataset's format;
      otherwise `--format-id`, else the format the labeler page preselects (`preferred_format`). It
      downloads it if needed, scores **every frame with every criterion** through the labeler cache (so
      scores match the pipeline and a changed criterion is re-scored), groups frames into scenes with the
      labeler's rows, and writes all scenes with all criteria's stats **only through the API**.
- [x] AC6: Populating inserts each scene with `insert_scene`; when that returns 409
      (the scene exists) every criterion's stats are set with `set_criterion_stats` and the scene's `claude`
      status is kept. Rerunning is idempotent (a rerun of unchanged data is all 204s and writes nothing),
      and a criterion added later is added to the existing scenes. The summary counts scenes inserted,
      updated and unchanged. The whole video is applied in one `batch()`.
- [x] AC7: `op`, `threshold` and `share_flagged` come from the production rule's condition on the
      criterion (today only `band > 180`); a criterion the production rule doesn't use has them all
      null and only `min/max/mean/std` filled. `std` is the population std (0 for a one-frame scene).
- [x] AC7a: Errors are reported, not hidden: a criterion with non-finite scores in a scene is left out
      of that scene and listed, a response of 400 or more is listed, and a failure to fetch or index the video is
      printed; the rest is still written. The command prints a count and each error, and exits non-zero
      if there was any.
- [x] AC8: Offline tests cover: insert/duplicate error, stats replace, lookup by frame locator
      (including first/last frame of a scene and a frame outside every scene), Claude status set and
      replace, atomic write leaving the old file intact when a write fails, the `.bak` copy, corrupt
      file rejection, `batch()` rollback, scene stats from synthetic scores, and idempotent populate
      with a fake index.

### Part 2 — Verification (later; to be detailed before implementation)

- [ ] AC9: Phase 1 selects scenes with `share_flagged == 0` whose `max` is close below the threshold
      and has Claude judge whether they are missed memes; phase 2 selects mixed scenes
      (`0 < share_flagged < 1`) and barely-flagged ones and has Claude judge whether they are false
      positives. Results go in through `set_claude_status`. A summary reports confirmed misses and
      false positives.

## Out of Scope

- Changing the production rule or threshold automatically; this only produces evidence.
- Extracting or saving the images of verified scenes (the labeler can open them).
- Multi-criterion rules; one criterion's stats per populate run.
- Writing verdicts back into `data/datasets/`.
- Part 2 (AC9) is not implemented yet.

## Technical Notes

- Lives in `tools/scene_analysis/` (dev-only, outside the package), built on `tools.labeling.index`
  and `tools.labeling.dataset`.
- Uses PyYAML (already in the `labeling` extra). Locking with `fcntl.flock` (macOS/Linux only; this
  is a dev tool).
- `claude` status is per scene, not per criterion: the verdict is about the image. Its `check` field
  records which question was asked (miss / false positive).

## Open Questions

- [ ] Q2: Default "close to the threshold" margin for Part 2: 20% of the threshold or absolute?
- [ ] Q3: Part 2: one frame per scene to Claude, or best + middle?
- [ ] Q4: Part 2: include fully flagged scenes with high `std` as "mixed"?

Resolved: Q1 — a single YAML file for all videos and criteria, accessed only through an API.
Q5 — CLI (assumed; not a labeler page).

## Changelog

- 2026-10-08: Draft written from the request: per-scene score stats, then Claude verification of
  near-threshold unflagged scenes (misses) and mixed / barely-flagged scenes (false positives).
- 2026-10-08: Requested: one YAML for all videos and criteria; build the database population first
  (analysis later); a Python API for insert-if-absent (error if present), select, update, and Claude
  status by frame locator, with the file never edited directly. Spec restructured into Part 1
  (store + populate, implemented) and Part 2 (verification, later).
- 2026-10-08: Implemented Part 1 (AC1–AC8): `tools/scene_analysis/` (`store.SceneStore`, `populate`, CLI), tests in
  `tests/test_scene_analysis.py`. Smoke-tested on 1qbqO8p1vLs (644 scenes; rerun updates, inserts nothing).
- 2026-10-08: Moved the scene database to data/datasets/scene_analysis/ (gitignored with datasets); confirmed the Claude verdict is per scene, independent of the criterion — spec Q resolved.
- 2026-10-08: Populate now scores every criterion in one run (no --criterion/--op/--threshold), picks the format as the labeler does (dataset's, else preferred_format), allows null condition fields for criteria without a production threshold, and reports errors with a non-zero exit. Smoke-tested on 1qbqO8p1vLs with a scratch database.
- 2026-10-08: Changed the file layout from a flat scene list to a tree (video → formats → scenes, version 2); scenes are keyed by their first frame instead of a scene index. Old-layout files are refused (no real database existed yet). Smoke-tested on 1qbqO8p1vLs with a scratch database.
- 2026-10-08: Renamed the scene's `frame` field to `first_frame` (file and API).
- 2026-10-08: `stats` is the last property of a scene (after `claude`).
- 2026-10-08: Added the root runner `populate_scenes.sh <video-id>... [--format-id] [--proxy] [--db]` (one or more videos; non-zero exit if any had errors).
- 2026-10-08: In a terminal, populate lists the video's formats (downloaded ones highlighted, else the labeler's default) and asks which to use (list number, format id, or Enter for the default); `--no-prompt` and non-terminal runs take the default; a video with a dataset stays pinned to its format. Listing checked live against lx011zFYIGU; nothing downloaded.
- 2026-10-08: The format prompt is now an arrow-key menu (up/down, PgUp/PgDn, Home/End, Enter, q/Esc cancels), starting on the default (downloaded format if any, else the labeler's), scrolling within the terminal height; typed answers remain when stdin isn't a terminal. Verified in a real pseudo-terminal.
- 2026-10-08: Operations return `Response(status, message, data)` with HTTP-style codes (200/201/204/400/404/409/500) instead of raising; `set_criterion_stats` is 201/200/204, so a rerun on unchanged data reports every scene as unchanged and doesn't rewrite the file. Populate's summary now also counts unchanged scenes.
