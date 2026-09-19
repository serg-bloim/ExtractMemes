# 018 — Persist `processed_vids.txt` on a Separate Orphan `data` Branch

**Date:** 2026-09-18
**Status:** Accepted

## Context

ADR 016 (decision 2) had `check-new-video.yml` commit `data/processed_vids.txt` back to whatever
branch triggered the workflow, on `main`. Every processed video adds a bot commit to `main`'s
history, interleaved with real code changes. The user wants that bookkeeping history kept
separate: `processed_vids.txt` should live on its own orphan branch, `data`, with `main`'s history
staying code-only.

## Decision

1. **`processed_vids.txt` moves to an orphan branch named `data`**, unrelated history to `main`.
   Removed from `main` (`git rm data/processed_vids.txt`) rather than kept as a stale duplicate.
2. **`check-new-video.yml` checks out `data` a second time, into a side folder.** A second
   `actions/checkout@v4` step (`ref: data`, `path: data-branch`) runs alongside the existing
   checkout of the code. Both `find` and `mark-processed` are pointed at
   `data-branch/processed_vids.txt` via the existing `--processed-file` option. The
   commit-and-push step runs inside `data-branch/`, against the `data` branch, independent of
   whichever ref triggered the workflow on the code checkout.
3. **No change to `playlist_watch.py` itself.** `--processed-file` already accepted an arbitrary
   path, and `read_processed` already treated a missing file as an empty set — both landed with
   the original implementation (`specs/features/playlist-watch.md` AC2, AC5, AC6). Only the
   workflow's checkout/commit steps needed to change.

## Options Considered

- **Keep committing to `main`, as ADR 016 decided** — rejected: was the original approach, but the
  user wants code history and bookkeeping history separated.
- **`actions/cache` or a release asset instead of a tracked file** — reconsidered and rejected
  again, same reasoning as ADR 016 decision 2: more moving parts than a small tracked file
  justifies.
- **A local `git worktree` checking out `data` into a side folder for interactive/manual use** —
  raised first, then dropped: the user's actual goal was the GitHub Actions workflow's checkout
  behavior, not a local dev-environment setup. `actions/checkout@v4`'s `ref`/`path` options give
  the workflow the same "two branches, two folders" shape without local worktree machinery.

## Consequences

- `main`'s commit history no longer includes per-video bookkeeping commits.
- The `data` branch's entire history is bot commits appending one line at a time — never merged
  back into `main`, never intended to be.
- **The `data` branch does not exist in the repository yet.** It must be created (an orphan branch
  seeded with an initial `processed_vids.txt`, or genuinely empty since `read_processed` tolerates
  a missing file) and pushed to `origin` before `check-new-video.yml` can run — its second
  checkout step (`ref: data`) fails otherwise. This is a manual, one-time setup step outside the
  workflow itself.
- Anyone inspecting processed-video history needs to know to look at the `data` branch, not `main`.

## References

- [specs/features/playlist-watch.md](../specs/features/playlist-watch.md)
- [ADR 016 — Watch a Playlist via a Manually-Triggered GitHub Actions Workflow](016-scheduled-playlist-watcher.md)
  (supersedes decision 2)
