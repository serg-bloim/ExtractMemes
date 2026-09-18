# 016 — Watch a Playlist via a Manually-Triggered GitHub Actions Workflow

**Date:** 2026-09-18
**Status:** Accepted

## Context

Running `extract-memes` against a new source video was a fully manual step. The channel this
targets publishes on a recurring pattern (`schedule.txt`), so the next iteration is to check a
playlist automatically and launch the pipeline on whatever's new — but several things needed
deciding: where this runs, how it persists state across GitHub Actions' ephemeral runners, where
the playlist is configured, and what triggers it.

## Decision

1. **Run natively on the GitHub-hosted runner (`pip install -e .`), not via the published Docker
   image.** `yt-dlp` is deliberately unpinned in `pyproject.toml` and needs frequent updates as
   YouTube changes its extraction quirks; the Docker image only rebuilds on `v*` tag pushes
   (ADR 013), so it could run for weeks against a stale `yt-dlp`. A fresh install always pulls the
   latest release from PyPI.
2. **Persist `data/processed_vids.txt` by committing it back to the repo.** The workflow appends a
   video id after a successful run and pushes the commit using its own `GITHUB_TOKEN`
   (`permissions: contents: write`). Small, human-readable, and needs no extra infrastructure
   (`actions/cache`, release assets) — the cost is one bot commit per processed video.
3. **Configure the playlist URL as a repository variable** (`vars.PLAYLIST_URL`), not a secret —
   it isn't sensitive, and it can be changed from repo settings without touching a workflow file.
4. **Trigger via `workflow_dispatch` only, for now — no cron.** A good schedule needs *variable*
   cadence (denser checks during the likely-upload windows already characterized in
   `schedule.txt`, sparser the rest of the week), which is its own design problem. Shipping manual
   triggering first keeps this iteration small; scheduled triggering is a planned follow-up.

See [specs/features/playlist-watch.md](../specs/features/playlist-watch.md) for the full
acceptance criteria.

## Options Considered

- **Run via the published Docker image** — rejected for now (Decision 1): simpler workflow (no
  `setup-python`/`setup-node` steps), but risks a stale `yt-dlp` between tagged releases, which
  matters more for a script whose whole job is scraping YouTube.
- **Persist processed-video state via `actions/cache` or a release asset** — rejected (Decision 2):
  avoids bot commits, but adds moving parts (cache eviction semantics, or upload/download steps)
  for a problem a plain tracked file already solves adequately.
- **Cron trigger with a fixed cadence now** (e.g. hourly) — deferred (Decision 4): doesn't reflect
  that uploads cluster in specific windows; the user preferred to design the variable-cadence
  schedule as its own follow-up rather than ship a naive fixed interval now.

## Consequences

- Every successful run adds a commit to whatever branch triggered the workflow — expected, and
  small in volume (one video at a time).
- Nothing runs automatically yet; someone still has to click "Run workflow" until the follow-up
  scheduling iteration ships.
- The workflow depends on `vars.PLAYLIST_URL`, `secrets.TELEGRAM_BOT_TOKEN`, and
  `secrets.TELEGRAM_CHAT_ID` being configured in the repo before first use.
- `--classifier claude` isn't available in this workflow (no authenticated `claude` CLI on the
  runner, same constraint as the Docker image per ADR 012) — it always runs
  `--classifier heuristic`.

## References

- [specs/features/playlist-watch.md](../specs/features/playlist-watch.md)
- [ADR 012 — Package ExtractMemes as a Docker Image](012-docker-image.md)
- [ADR 013 — Publish the Docker Image via GitHub Actions on Tag Push](013-github-actions-docker-publish.md)
- [ADR 014 — Upload Extracted Memes to Telegram as a Pipeline Stage](014-telegram-upload-as-pipeline-stage.md)
- `schedule.txt` — the channel's observed upload-time pattern, motivating the variable-cadence
  follow-up
