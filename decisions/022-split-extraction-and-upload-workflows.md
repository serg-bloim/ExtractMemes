# 022 — Split the Watch Workflow into Extraction and Upload, with a Status per Video

**Date:** 2026-10-23
**Status:** Accepted

## Context

`check-new-video.yml` extracted a video's memes and uploaded them to Telegram in one run, and marked
the video processed only if both succeeded. Extraction is the expensive part, but an upload failure
discarded it: the next run extracted the same video again.

## Decision

1. **Two workflows, scheduled separately.** `check-new-video.yml` only extracts: it no longer passes
   `--upload-to`, and it always commits `runs/<video-id>/clean/` to the `data` branch. The new
   `upload-memes.yml` (every 30 minutes) uploads from those committed images.
2. **`processed_vids.txt` holds a status per video**, one `<video id> <status>` line each: `extracted`
   (set by the extraction workflow) and `uploaded` (set by the upload workflow). A line with only an id
   is a video from before statuses and counts as `uploaded`, so the existing file needs no migration.
   `find` skips every recorded video whatever its status.
3. **The upload workflow takes up to 5 `extracted` videos per run, oldest first**, and stops at the
   first failure. A failed video keeps `extracted` and is retried by the next run. A video with no
   committed `clean/` images (no memes found; git keeps no empty folders) is marked `uploaded`.
4. **Statuses are applied after syncing with the `data` branch** (`.github/scripts/push-data.sh`). Both
   workflows push to `data`, and a status change in the middle of the file conflicts with an append
   next to it. The Python steps therefore only write the ids they finished to a file in
   `$RUNNER_TEMP`; the script re-applies the run's other changes onto the latest `data`, sets the
   statuses on that fresh copy and pushes, retrying if the push is rejected.
5. **`SAVE_CLEAN` is gone**: the clean images are the hand-off between the two workflows.

## Consequences

- An upload failure no longer costs a re-extraction.
- The `data` branch grows by the clean images of every video.
- The upload workflow installs only `yt-dlp`, `tqdm` and `requests`, and does nothing else unless the
  status file has an `extracted` line.
- The pipeline's own `--upload-to` stays for local runs.

## References

- [specs/features/upload-extracted-memes.md](../specs/features/upload-extracted-memes.md)
- [specs/features/playlist-watch.md](../specs/features/playlist-watch.md)
- [ADR 018](018-processed-videos-on-orphan-data-branch.md)
