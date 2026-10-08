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
  `first_frame..last_frame` contains the frame. A scene's own key is `(video_id, format_id, scene_index)`.
- **Criterion stats**: for one criterion and its condition (`op`, `threshold`, default the production
  rule's, `band > 180`), the scene's score `min`, `max`, `mean`, `std` and `share_flagged` (fraction of
  frames for which the condition holds).

## Acceptance Criteria

### Part 1a — Scene database

- [x] AC1: One YAML file, `data/datasets/scene_analysis/scene_analysis.yaml` (gitignored with `data/datasets/`), holds all videos and criteria.
      Each scene entry has: `video_id`, `format_id`, `scene_index`, `first_frame`, `last_frame`,
      `start_ts`, `end_ts`, `frame_count`, `stats` (a map criterion name → `op`, `threshold`, `min`,
      `max`, `mean`, `std`, `share_flagged`) and `claude` (null until checked).
- [x] AC2: All access goes through the Python API `tools/scene_analysis/store.py` (`SceneStore`);
      no other code reads or writes the file. The API offers at least:
      `insert_scene(...)` (raises `SceneExistsError` if the key exists, leaving the file untouched),
      `set_criterion_stats(video_id, format_id, scene_index, criterion, stats)` (adds or replaces one
      criterion's stats), `get_scene(video_id, format_id, scene_index)`,
      `find_scene(video_id, format_id, frame_index)` (by frame locator; `SceneNotFoundError` if none),
      `select_scenes(predicate)` (all scenes matching a function), and
      `set_claude_status(video_id, format_id, frame_index, verdict, reason, check)` addressed by
      frame locator (`verdict`: `meme` | `not_meme` | `unsure`; `check`: `miss` | `false_positive`;
      it stamps `checked_at`; replaces a previous status).
- [x] AC3: Corruption safety: every write is atomic (written to a temp file in the same directory,
      flushed to disk, then renamed over the file), the previous version is kept as
      `scene_analysis.yaml.bak`, concurrent writers are serialized with a lock file, and a file that
      does not parse or does not match the schema makes the API raise `SceneStoreError` without
      writing anything. `with store.batch():` applies many operations with one read and one write
      and writes nothing if the block raises.
- [x] AC4: Values are stored as plain YAML numbers/strings (numpy types converted), and a stored
      scene round-trips unchanged.

### Part 1b — Population

- [x] AC5: `python -m tools.scene_analysis populate <url-or-id> [--criterion band] [--op OP --threshold T]
      [--format-id ID] [--proxy URL]` fetches the video (the dataset's exact format if the video has a
      dataset, else `--format-id`, else the worst format), scores every frame through the labeler
      cache (so scores match the pipeline and a changed criterion is re-scored), groups frames into
      scenes with the labeler's rows, and writes them to the database **only through the API**.
- [x] AC6: Populating inserts each scene with `insert_scene`; when it already exists
      (`SceneExistsError`) the criterion's stats are replaced with `set_criterion_stats` and the
      scene's `claude` status is kept. Rerunning is therefore idempotent, and populating a second
      criterion adds to the same scenes. The whole video is applied in one `batch()`.
- [x] AC7: `--op/--threshold` default to the production classifier's condition on the criterion; a
      criterion the production rule doesn't use requires both. `score_std` is the population std
      (0 for a one-frame scene).
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
