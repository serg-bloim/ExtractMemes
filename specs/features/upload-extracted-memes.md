---
title: "Upload Extracted Memes in a Separate Workflow"
status: implemented
created: 2026-10-23
updated: 2026-10-23
author: ""
depends-on: ["playlist-watch", "meme-upload"]
---

# Upload Extracted Memes in a Separate Workflow

## Problem Statement

Extraction is expensive and the Telegram upload is cheap but fails now and then. Run together, an
upload failure threw the extraction away. Extraction and upload must be separate workflows, each on
its own schedule, and the processed-videos file must record how far each video got.

## User Story

As the operator, I want extraction and upload to run independently and a failed upload to be retried
on its own, so that the expensive extraction never repeats.

## Acceptance Criteria

- [x] AC1: `processed_vids.txt` has one `<video id> <status>` line per video; status is `extracted` or
      `uploaded`. A line with only an id reads as `uploaded`. `playlist_watch.read_processed` returns
      `video id -> status`; `set_status(path, id, status)` replaces the video's line in place or appends
      one, atomically. CLI: `set-status STATUS [VIDEO_ID...] [--ids-file F]` (a missing file adds no
      ids) replaces `mark-processed`. `find` skips any recorded video.
- [x] AC2: `check-new-video.yml` runs the pipeline without `--upload-to`, always keeps `clean/` in
      `runs/<id>/`, and after a successful run sets the video to `extracted`. A failed run records
      nothing, so the video is found again.
- [x] AC2a: After a successful run that extracted a video, and after the data push, the last step starts
      `upload-memes.yml` with `gh workflow run` on the same ref (the job has `actions: write`). The upload
      schedule stays as the retry path.
- [x] AC3: `python -m extract_memes.playlist_watch pending --limit N [--processed-file F]` prints the ids of
      up to `N` videos with status `extracted`, oldest first, one per line. It is the only place the
      pending videos are chosen.
      `python -m extract_memes.upload_pending ID... --runs-dir D --done-file X [--proxy URL]` uploads
      `D/<id>/clean/meme_*.png` of the given videos, in the given order, through `TelegramUploader` (source
      `https://youtu.be/<id>`, title and thumbnail fetched, upload still done if that fetch fails). It
      appends each id to `X` right after its upload, stops at the first failure (non-zero exit) and never
      reads or edits the status file. A video with no images counts as done without posting.
- [x] AC4: `upload-memes.yml` runs every 30 minutes and on demand. It checks out `data` sparsely
      (`/processed_vids.txt`), installs `yt-dlp tqdm requests opencv-python-headless numpy` and the package
      without dependencies, and picks up to 5 ids with the first command of AC3. It adds
      `/runs/<id>/clean/` to the sparse checkout for exactly those ids, and does nothing more when there are
      none. Otherwise it passes the same ids to the second command of AC3 with
      `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`, and sets the ids in `X` to `uploaded` even when the upload
      step failed part-way.
- [x] AC5: `.github/scripts/push-data.sh MESSAGE [STATUS IDS_FILE]` commits the run's changes in
      `data-branch`, then (up to 5 attempts) re-applies them on the latest `data`, sets the statuses and
      pushes, so the two workflows' pushes don't conflict.
- [x] AC6: `check-new-video.yml` checks out `data` with a non-cone sparse checkout of
      `/processed_vids.txt` and `/upload_dates.json`; `push-data.sh` stages with `git add --sparse -A`.
- [x] AC7: Tests in `tests/test_playlist_watch.py` and `tests/test_upload_pending.py`.

## Out of Scope

- Pruning old `runs/` folders from the `data` branch.
- Retrying a failed video within the same run.

## Changelog

- 2026-10-23: The user asked to split extraction and upload into two separately scheduled workflows and
  to track a status (`extracted`, `uploaded`) per video; the uploader handles up to 5 videos per run and
  retries a failed one next time. Decisions in [ADR 022](../../decisions/022-split-extraction-and-upload-workflows.md).
  Defaults I chose: upload every 30 minutes; extraction keeps its 2-hour schedule; the uploader stops at
  the first failure. **Verified:** `pytest -m "not slow"` passes except the two `tests/test_cli.py` cases
  that need the `extract-memes` script on `PATH`; `push-data.sh` was run against a local bare repository,
  including a push race. The workflows were not run on GitHub.
- 2026-10-23: The user asked for a sparse checkout of the `data` branch, since extraction only needs the
  status file. Applied to the extraction workflow only (AC6); the upload workflow would need the status file first, then the image folders, so it keeps the full checkout for now; `push-data.sh` needed `--sparse` to stage the new run
  folder, tested against a local sparse clone with a push race. Not run on GitHub.
- 2026-10-23: The user asked to start the upload workflow right after a successful extraction (AC2a),
  by dispatching it as the last step. Not run on GitHub.
- 2026-10-23: The upload workflow now checks out the `data` branch sparsely: the status file first, then
  `runs/<id>/clean/` for each of the first 5 `extracted` videos (matching `--limit 5`). It also installs
  `opencv-python-headless` and `numpy`, which `telegram_uploader` needs since the JPEG re-encoding
  ([meme-upload](meme-upload.md) AC27). Checkout steps tested on a local clone. Not run on GitHub.
- 2026-10-23: The user pointed out that the pending videos were chosen twice, in bash and in Python.
  Added `playlist_watch pending` (the one place that picks them); the workflow runs it once, fetches
  those folders, and passes the ids to `upload_pending`, which no longer reads the status file or takes
  `--limit`/`--processed-file`. Amended AC3 and AC4. Tests moved/added; not run on GitHub.
