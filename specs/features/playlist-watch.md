---
title: "Watch a Playlist and Run the Pipeline on the Oldest New Video"
status: implemented
created: 2026-09-18
updated: 2026-09-18
author: ""
depends-on: ["extraction-pipeline", "meme-upload"]
---

# Watch a Playlist and Run the Pipeline on the Oldest New Video

## Problem Statement

Running `extract-memes` against a new source video is currently a manual step: someone has to
notice a new video exists, copy its URL, and invoke the CLI by hand. For a channel that publishes
on a recurring pattern (see `schedule.txt`), this should instead be checked for automatically and
run without a human in the loop — but only for videos that haven't already been processed, and
only one at a time.

## User Story

**Primary:**
As the operator of this pipeline, I want a workflow I can trigger that checks a known playlist for
the oldest video not yet processed and runs the full extraction+upload pipeline on it, so that
publishing a new video doesn't require me to manually find and launch a run.

## Acceptance Criteria

### Library: `src/extract_memes/playlist_watch.py`

- [x] AC1: `list_playlist_video_ids(playlist_url: str, count: int) -> list[str]` fetches metadata
      only (yt-dlp with `extract_flat="in_playlist"`, `playlistend=count`, no per-video extraction
      and no download) and returns up to `count` video ids in the order yt-dlp reports them.
      `yt_dlp` is imported lazily inside the function, matching `downloader.download`'s pattern, so
      importing `playlist_watch` has no import-time side effects.
- [x] AC2: `read_processed(path: Path) -> set[str]` reads one video id per non-blank line;
      returns an empty set if `path` doesn't exist yet.
- [x] AC3: `append_processed(path: Path, video_id: str) -> None` appends one line with `video_id`,
      creating parent directories and the file if they don't exist. No dedup check — the caller is
      responsible for only calling this once per newly processed video.
- [x] AC4: `find_next_unprocessed(video_ids: list[str], processed: set[str]) -> str | None` scans
      `video_ids` from the end (the oldest entry in the fetched batch) towards the start (the
      newest), returning the first id not in `processed`. Returns `None` if every fetched id is
      already processed. This assumes `video_ids` is newest-first, true for a channel's
      auto-generated "Uploads" playlist (see Out of Scope).

### CLI: `python -m extract_memes.playlist_watch`

- [x] AC5: `find --playlist-url URL [--count N] [--processed-file PATH]` (defaults: `count=8`,
      `processed-file=data/processed_vids.txt`) combines AC1/AC2/AC4 and prints the chosen video id
      to stdout with no other output — or prints nothing and exits 0 if none is found — so a
      workflow step can capture it directly.
- [x] AC6: `mark-processed VIDEO_ID [--processed-file PATH]` (default `processed-file` as above)
      calls `append_processed`.

### Workflow: `.github/workflows/check-new-video.yml`

- [x] AC7: Triggered only by `workflow_dispatch` (manual) for now — see Out of Scope for scheduled
      triggering. Permissions: `contents: write` (needed to push the updated processed-file back).
      Steps:
      1. `actions/checkout@v4`.
      2. `actions/setup-python@v5` (3.14).
      3. `pip install yt-dlp && pip install --no-deps -e .` — installs only what `find` actually
         needs (`yt_dlp`, plus the local package itself so `python -m extract_memes.playlist_watch`
         is importable), skipping `opencv-python-headless`/`numpy`/`static-ffmpeg`/`tqdm`/`requests`
         entirely for a run that finds nothing new (see Technical Notes).
      4. Run `python -m extract_memes.playlist_watch find --playlist-url "${{ vars.PLAYLIST_URL }}"`,
         capturing stdout into a step output (e.g. `video_id`) via `$GITHUB_OUTPUT`.
      5. Only if `video_id` is non-empty:
         - `actions/setup-node@v4` — Node.js is required by `extract-memes` itself for YouTube
           downloads (ADR 006); not needed for step 4's flat playlist listing.
         - `pip install -e .` (now installs the full dependency set fresh, including the latest
           `yt-dlp` from PyPI — see Technical Notes on why this runs natively rather than via the
           published Docker image).
         - `extract-memes "https://youtu.be/$video_id" --classifier heuristic --upload-to telegram`
           with `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` from repo secrets.
      6. If step 5 succeeded: run `python -m extract_memes.playlist_watch mark-processed "$video_id"`.
      7. If `data/processed_vids.txt` has uncommitted changes: commit (bot identity,
         e.g. `github-actions[bot]`) and push.
      A run where `find` returns nothing does only steps 1–4 and ends there — no error.

### Tests

- [x] AC8: `tests/test_playlist_watch.py` covers `read_processed`/`append_processed`/
      `find_next_unprocessed` as pure functions (no network, no git) — missing processed-file,
      newest-first scanning order, "all already processed" returning `None`, and
      `list_playlist_video_ids` with yt-dlp's `YoutubeDL` faked out (never hits the network),
      asserting the `extract_flat`/`playlistend` options passed. Runs under `pytest -m "not slow"`.

## Out of Scope

- **Scheduled (cron) triggering.** This ships `workflow_dispatch` only. The user specifically asked
  to defer this: a good schedule needs *variable* cadence (denser checks during the likely-upload
  windows already characterized in `schedule.txt`, sparser the rest of the week), which is its own
  design problem — planned as a follow-up iteration once manual triggering is validated.
- **Arbitrary, manually-ordered playlists.** `find_next_unprocessed`'s "oldest of the fetched batch"
  logic (AC4) only makes sense for a playlist that is itself newest-first, e.g. a channel's
  auto-generated Uploads playlist. A hand-curated playlist isn't the target use case.
- **Automatic retry of a failed `extract-memes` run within the same workflow invocation.** A failed
  run (step 5) simply isn't marked processed (step 6 is skipped), so the *next* manual trigger picks
  the same video back up. No in-workflow retry loop.
- **Concurrency control.** Two overlapping workflow runs racing on the same video (double-processing,
  or a push conflict on `data/processed_vids.txt`) isn't handled — acceptable for a manually-triggered,
  single-operator workflow. Revisit if/when triggering becomes automatic.
- **A standalone GitHub Actions "variable" fallback for `PLAYLIST_URL`.** If it's unset the `find`
  step simply fails with yt-dlp's own error; no extra validation layer is added around it.

## Technical Notes

- **Why install on the runner instead of the already-published Docker image:** raised by the user —
  `yt-dlp` is deliberately unpinned in `pyproject.toml` and needs frequent updates as YouTube changes
  its extraction quirks, but the Docker image only rebuilds on `v*` tag pushes (ADR 013). A fresh
  `pip install -e .` on every run always pulls the latest `yt-dlp` from PyPI, which matters more here
  than skipping a `setup-python`/`setup-node` step.
- **Why `--classifier heuristic` in the workflow:** `--classifier claude` requires an interactively
  authenticated `claude` CLI (ADR 012's Dockerfile explicitly doesn't bundle it, for the same
  reason), which isn't available on a GitHub-hosted runner.
- **Why commit-and-push instead of `actions/cache` or a release asset:** the user chose this —
  `data/processed_vids.txt` is a small, human-readable file; a bot commit per processed video is an
  acceptable, visible cost in exchange for simplicity (no cache-eviction or asset-upload machinery).
  It's tracked in git (not gitignored — CLAUDE.md's Gitignore list doesn't cover `data/`, matching
  `data/labeled_dataset/` per ADR 008).
- **Why a repository variable for the playlist URL:** the user chose this — `vars.PLAYLIST_URL` is
  not secret, and keeping it in repo settings means changing the target playlist doesn't require a
  code change.
- `count` (playlist fetch depth) defaults to 8, inside the user-requested 5–10 range.
- **Why the install is split in two (`pip install yt-dlp` + `--no-deps -e .`, then the full
  `pip install -e .` only if a video was found):** raised by the user — if this workflow ends up
  triggered often (checking) while actually downloading/processing rarely, paying for
  `opencv-python-headless`/`numpy`/`static-ffmpeg` (tens of MB combined, plus a bundled ffmpeg
  binary) on every single check is wasted time when nothing new is usually there.
  `playlist_watch.py` only ever imports `yt_dlp`, so the cheap install is enough for `find` to run;
  the heavy dependencies are deferred to the one branch that actually needs them.

## Open Questions

Resolved by the user (2026-09-18):

- Q1: Run the workflow via the published Docker image, or install fresh on the runner? **Install on
  the runner** — keeps `yt-dlp` current; the Docker image only rebuilds on version tags.
- Q2: How should `data/processed_vids.txt` persist across ephemeral runners? **Commit and push it
  back to the repo** as part of the workflow.
- Q3: Where is the playlist URL configured? **A repository variable** (`vars.PLAYLIST_URL`), passed
  into the workflow.
- Q4: What triggers the workflow, and on what cadence? **Manual (`workflow_dispatch`) only, for
  now.** The user wants to add scheduled triggering later, with denser checks during the
  likely-upload windows from `schedule.txt` and sparser checks the rest of the time — deferred as
  its own follow-up rather than built now.

## Changelog

- 2026-09-18: The user asked to run the pipeline via GitHub Actions, triggered by a new script that
  checks a playlist (metadata only, latest 5–10 videos) against a repo-tracked
  `data/processed_vids.txt`, and launches the main pipeline on the oldest unprocessed video found.
  No spec existed for this yet. Surveyed the existing CLI (`__main__.py`), `downloader.py`'s
  yt-dlp/lazy-import conventions, and ADRs 012/013 (Docker image + its publish workflow) before
  drafting. Put the open architectural questions to the user: run environment (Docker vs. native
  install — user picked native, to keep `yt-dlp` current since the Docker image only rebuilds on
  tags), state persistence (commit-back), playlist source (repo variable), and trigger cadence (user
  asked to start with manual `workflow_dispatch` only and defer variable-cadence scheduling as a
  follow-up). Wrote this spec as `ready` with all four resolved.
- 2026-09-18: Implemented.
  - **Library:** `src/extract_memes/playlist_watch.py` — `list_playlist_video_ids` (AC1, lazy
    `yt_dlp` import, `extract_flat`/`playlistend`), `read_processed`/`append_processed` (AC2, AC3),
    `find_next_unprocessed` (AC4), plus a `find`/`mark-processed` argparse CLI (AC5, AC6).
  - **Workflow:** `.github/workflows/check-new-video.yml` (AC7) — `workflow_dispatch` only,
    `contents: write`, checkout → setup-python 3.14 → setup-node → `pip install -e .` → `find` →
    conditional `extract-memes ... --classifier heuristic --upload-to telegram` → conditional
    `mark-processed` → conditional commit-and-push of `data/processed_vids.txt`. A failed
    `extract-memes` step fails the job and skips the remaining steps, so the video isn't marked
    processed.
  - Created the tracked, initially-empty `data/processed_vids.txt`.
  - Wrote [ADR 016](../../decisions/016-scheduled-playlist-watcher.md) for the four resolved
    decisions (run environment, state persistence, playlist source, trigger cadence).
  - **Tests:** `tests/test_playlist_watch.py` (AC8) — pure-function coverage for
    `read_processed`/`append_processed`/`find_next_unprocessed`, `list_playlist_video_ids` with
    `yt_dlp.YoutubeDL` mocked out, and both CLI subcommands. No network or git access.
  - **Verified:** `pytest -m "not slow"` — 193 passed (was 180 before this change), no test hits
    the network. The workflow YAML itself wasn't run against real GitHub Actions in this session
    (needs `vars.PLAYLIST_URL` and the Telegram secrets configured in the repo first) — reviewed
    by inspection only.

  All ACs are checked. Status `implemented`.
- 2026-09-18: The user asked how much overhead installing all dependencies adds if the workflow
  ends up checking frequently but downloading/processing rarely. Pointed out `playlist_watch.py`
  only needs `yt_dlp`, while `pip install -e .` pulls in `opencv-python-headless`/`numpy`/
  `static-ffmpeg` regardless. The user asked to restructure accordingly: `check-new-video.yml`
  (AC7) now installs only `yt-dlp` plus the local package via `--no-deps` for the `find` step, and
  defers `setup-node` and the full `pip install -e .` to the conditional branch that runs only once
  a video is actually found. Updated this spec's AC7 and Technical Notes to match; no ADR needed
  (a routine, easily-reversible refinement of the already-decided "install natively" architecture
  from ADR 016, not a new decision).
