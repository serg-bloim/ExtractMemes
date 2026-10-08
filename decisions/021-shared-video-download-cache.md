# 021 — One Shared Video Download Cache, Keyed by Video ID and Format ID

**Date:** 2026-10-08
**Status:** Accepted (the labeler already follows it; the pipeline and CLI do not yet — see Consequences)

## Context

Several tools download the same videos: the pipeline/CLI (`extract-memes`), the labeler, the
evaluation and scene-analysis tools, `run_real_video.py`, and the playgrounds. Today they do not
share files:

- the pipeline downloads to `downloads/<video-id>_worst.<ext>` and `<video-id>_best.<ext>` (the
  CLI's `--downloads-dir` defaults to `downloads/`), named after a quality *tier*;
- the labeler and the tools built on it download to `.runtime/downloads/<video-id>_<format-id>.<ext>`
  (`tools/labeling/dataset.py`), named after the exact yt-dlp format.

So a video fetched by one tool is fetched again by the other, and `_worst` / `_best` do not say which
format they hold: "worst" can resolve to different formats over time, and two tools that want
different resolutions of one video need files that cannot overwrite each other.

yt-dlp does not keep a cache of its own. What it does is skip the transfer when a finished file
already exists at the output path it computes. That only helps if every caller computes the same path.
The sharing therefore comes from agreeing on one directory and one filename rule, not from a
yt-dlp feature we have to configure.

## Decision

1. **One directory.** Videos are downloaded to `.runtime/downloads/` by default, in every tool
   (pipeline, CLI, labeler, evaluation, scene analysis, playgrounds, `run_real_video.py`). The
   directory stays overridable (`--downloads-dir`, a function argument), but nothing sets a different
   default. `.runtime/` is already gitignored.
2. **One filename rule.** `<video-id>_<format-id>.<ext>`, i.e. yt-dlp's
   `%(id)s_%(format_id)s.%(ext)s`. The format id is the concrete yt-dlp format id of what was
   downloaded (for example `269`), never a tier name such as `worst` or `best`. Different formats of
   one video are different files, so a tool that needs a low resolution and a tool that needs a high
   one never overwrite or replace each other.
3. **Reuse before downloading.** Before any network request, a downloader that knows the format id
   looks for `<dir>/<video-id>_<format-id>.<ext>`; if the file exists and is usable (it opens, and
   its width, height, fps and frame count match what is expected when the caller knows them, as
   `validate_video` does for a dataset), it is returned and nothing is fetched. A file that fails
   validation is re-downloaded, not trusted.
4. **Tiers are resolved to a format id first.** `worst` / `best` are selectors, not identities. A
   caller that starts from a tier resolves it to a concrete format id with a metadata-only lookup
   (`skip_download`) and then applies rules 2 and 3 to that id. The lookup needs the network; the
   transfer does not happen when the file is cached. When a tool is re-run for a video it has already
   seen, it can record the format id it used and skip even the lookup.
5. **Cached files are never deleted automatically.** They are large and are the point of the cache.
   Cleaning `.runtime/downloads/` is a manual step.

## Options Considered

- **Keep per-tool directories** (`downloads/` for the pipeline, `.runtime/downloads/` for dev tools).
  Rejected: duplicated multi-hundred-megabyte files and repeated downloads, which also repeat the
  bot-check and proxy problems of [ADR 017](017-macos-local-network-proxy-relay.md).
- **Name files by tier** (`_worst`, `_best`). Rejected: a tier is not a format, so the name does not
  identify the content, and a tier can map to different formats between runs.
- **A separate cache index (database or manifest).** Rejected as unnecessary: the filename already
  encodes the identity and the file itself can be validated.
- **Rely on yt-dlp's `--no-overwrites` / archive options only.** Insufficient: they still depend on
  every caller choosing the same output path, which is exactly what this decision fixes. yt-dlp still
  performs its metadata request even when it then skips the transfer, so an explicit existence check
  is what avoids the network.

## Consequences

- Moving the pipeline and CLI onto this scheme is follow-on work, not done by this ADR:
  `download()` in `src/extract_memes/downloader.py` and the `downloads_dir` defaults in `pipeline.py`
  and `__main__.py` currently use `downloads/` and `_worst` / `_best`. It needs a spec (the
  `video-download` spec) update and a migration note: old `downloads/` files are not found by the new
  rule and can be deleted.
- Because the filename now carries the format id, the pipeline's scan pass and extract pass
  automatically use different files, as before, but a labeler session on the same format reuses the
  pipeline's scan download (and vice versa).
- The labeler's `download_format` always calls yt-dlp today and relies on `ensure_video` to skip a
  dataset video that is already present; rule 3 generalises that check to every caller.
- Disk use grows with the number of distinct (video, format) pairs. Nothing prunes it.
- Documents that name the old layout (`CLAUDE.md` directory tree, `playground/` docstrings, the
  video-download spec) need updating when the pipeline is migrated.

## References

- [ADR 006](006-youtube-video-only-formats-and-download-toolchain.md) — YouTube download toolchain.
- [ADR 004](004-claude-classifier-and-dual-resolution-download.md) — scan low-res, extract high-res.
- [ADR 005](005-runtime-layout-and-classifier-checkpoint.md) — `.runtime/` layout.
- `tools/labeling/dataset.py` (`downloaded_path`, `download_format`, `ensure_video`) — the current
  implementation of the filename rule.
