---
title: "Video Download"
status: implemented
created: 2026-09-16
updated: 2026-09-18
author: ""
depends-on: ["project-setup"]
---

# Video Download

## Problem Statement

Before the pipeline can read frames, the source video has to be on disk, in two versions: a
small, fast copy to scan for meme timecodes, and the highest-quality copy available to extract the
final meme images from (see [ADR 004](../../decisions/004-claude-classifier-and-dual-resolution-download.md)).
YouTube no longer serves pre-muxed video+audio formats for typical videos, and it requires a
JavaScript runtime to list formats. HLS downloads also need ffmpeg to become valid MP4 files
([ADR 006](../../decisions/006-youtube-video-only-formats-and-download-toolchain.md)). During
development, the same code path must also accept a local video file so the pipeline can run
offline.

## User Story

**Primary:**
As the ExtractMemes pipeline, I want to fetch a YouTube video at a requested quality tier (worst
or best), so that later stages can scan it cheaply or read it at full quality for final frame
extraction.

**Secondary:**
As the developer, I want to point the pipeline at a local video file instead of a URL, so that I
can validate the pipeline against `sample/short.mp4` without a network call.

## Acceptance Criteria

- [x] AC1: `src/extract_memes/downloader.py` exposes
      `download(source: str, quality: Literal["worst", "best"], dest_dir: Path) -> Path`. Callers
      (the pipeline) pass only `"worst"` or `"best"`, never raw yt-dlp format selectors.
- [x] AC2: When `source` is an existing local file (`Path(source).is_file()`), `download` returns
      that path unchanged. No network call, no copy, no ffmpeg setup; `quality` and `dest_dir`
      are ignored.
- [x] AC3: Otherwise `source` is treated as a URL and downloaded with `yt_dlp.YoutubeDL` using these
      format selectors:
      `worst` → `wv*[ext=mp4]/wv*`, `best` → `bv*[ext=mp4]/bv*`. That is, the worst/best format
      that contains video, preferring mp4. Audio isn't needed, and nothing is merged.
- [x] AC4: The downloaded file goes to `dest_dir/<video id>_<quality>.<ext>`, using yt-dlp output
      template `%(id)s_<quality>.%(ext)s`, e.g. `downloads/AElGyY97k_0_worst.mp4`. File names
      never contain `*` or other glob/shell metacharacters. Downloading the same URL at `worst`
      and at `best` produces two distinct files, and both are kept. The returned `Path` is the
      final file on disk (`ydl.prepare_filename(info)`).
- [x] AC5: The yt-dlp options include `js_runtimes={"node": {}}` (Node.js solves YouTube's JS
      challenges), `quiet=True`, and `noprogress=True` — yt-dlp's own console output stays
      suppressed; progress is shown by AC11 instead.
- [x] AC11: `download` shows a `tqdm` progress bar for a URL download, matching the
      `pipeline.run` convention of a `tqdm` bar per stage (extraction-pipeline AC6). The options
      include `progress_hooks=[hook]`, where `hook` updates the bar from yt-dlp's `"downloading"`
      events (`downloaded_bytes` against `total_bytes`, falling back to `total_bytes_estimate`
      when the real total isn't known yet) and tops the bar off to its total on the `"finished"`
      event. The bar's `desc` is `Downloading (worst)` / `Downloading (best)`. A local-file source
      (AC2) shows no bar — there's nothing to download.
- [x] AC6: Right before a URL download, `static_ffmpeg.add_paths()` is called so yt-dlp has ffmpeg
      and remuxes HLS output into a real MP4 container. Importing `extract_memes.downloader` (or
      anything that imports it, including the CLI's `--help`) and the local-file path of AC2
      **never** call it: no import-time side effects, no `PATH` changes, no binary download.
- [x] AC7: `dest_dir` is created (with parents) if it's missing, and only on the URL path.
- [x] AC8: If yt-dlp fails for any reason (bad URL, format not available, network error, local path
      typo that fell through to the URL path), `download` raises `RuntimeError` whose message
      includes the original `source` and `quality`, chained (`from exc`) to the underlying error.
- [x] AC9: Offline unit tests (no network) with `yt_dlp.YoutubeDL` and `static_ffmpeg.add_paths`
      mocked cover:
      local passthrough (returns the same path; `add_paths` not called; `YoutubeDL` not
      constructed);
      selector mapping for **both** `worst` and `best`;
      `outtmpl` ends with `%(id)s_worst.%(ext)s` / `%(id)s_best.%(ext)s` and contains no `*`;
      `js_runtimes` is set;
      `dest_dir` is created;
      a yt-dlp failure raises `RuntimeError` mentioning the source;
      importing the module doesn't call `add_paths`;
      and the yt-dlp options carry exactly one callable in `progress_hooks` (AC11).
      `_progress_hook`'s own behavior (bar total/position from `"downloading"` events, the
      `total_bytes_estimate` fallback, topping off on `"finished"`, and a `"finished"` event with
      no known total leaving the bar untouched) is tested directly against a real `tqdm` instance,
      without going through yt-dlp at all.
- [x] AC10: Tests marked `@pytest.mark.slow` download the permanent test video
      `https://youtu.be/AElGyY97k_0` into `tmp_path` at both qualities and assert: each returned
      file exists, is non-empty, has suffix `.mp4`, starts with an MP4 `ftyp` box (bytes 4–8 are
      `ftyp`), opens with `cv2.VideoCapture`, and the `best` file's frame height is at least the
      `worst` file's.
- [x] AC12: `download` accepts an optional `proxy: str | None = None` keyword argument. When set
      (and only on the URL path — AC2's local-file passthrough ignores it, same as `quality` and
      `dest_dir`), it's passed straight through as yt-dlp's `proxy` option, e.g.
      `socks5h://127.0.0.1:1080` for the LAN relay in
      [ADR 017](../../decisions/017-macos-local-network-proxy-relay.md), or an `http://` URL. No
      validation of the proxy URL's scheme or reachability — yt-dlp's own error surfaces through
      AC8's `RuntimeError` wrapping if it's bad. `pipeline.run` gains a matching `proxy: str | None
      = None` parameter and passes it to both the `"worst"` and `"best"` downloads (same proxy for
      both — the LAN relay in ADR 017 is a fixed local address, not a per-quality setting). The CLI
      gains `--proxy`, falling back to the `EXTRACT_MEMES_PROXY` environment variable when unset
      (same fallback pattern as `--telegram-bot-token`/`TELEGRAM_BOT_TOKEN`), default `None` (no
      proxy — yt-dlp's own `HTTPS_PROXY`/`HTTP_PROXY`/`NO_PROXY` environment handling still applies
      underneath when neither is set, since that's yt-dlp's existing default behavior, unchanged by
      this AC).

## Out of Scope

- Retry or backoff on network failure.
- Audio or subtitle downloads.
- Explicit caching logic. By default, yt-dlp already skips a download when the output file exists
  ("has already been downloaded"). Because file names are deterministic (`<id>_<quality>.<ext>`),
  re-running on the same URL reuses earlier downloads. This is accepted, incidental behavior, not
  a guarantee.
- Cookies, logins, age-restricted, private, or members-only videos.
- Non-YouTube sites. yt-dlp may handle them, but they're untested and unsupported.

## Technical Notes

- **Runtime dependencies introduced by this spec:** `yt-dlp` (known-good 2026.8.19) and
  `static-ffmpeg` (known-good 3.0). AC11's progress bar needs no new dependency: `tqdm` was already
  declared for extraction-pipeline's scan/extract bars.
- **Why a `tqdm` bar via `progress_hooks` instead of just flipping `noprogress=False`** (AC11):
  yt-dlp's own built-in progress renderer writes its own formatted line straight to the terminal,
  inconsistent with every other stage's `tqdm` bar. Driving a `tqdm` bar from `progress_hooks`
  keeps one consistent progress-reporting style for the whole run, and it works whether or not
  `quiet`/`noprogress` are set, since it doesn't depend on yt-dlp's own console output at all.
- **External prerequisite for URL sources:** Node.js on `PATH` (known-good v26.8.2). No system
  `ffmpeg`, and no `deno`.
- Import `yt_dlp` and `static_ffmpeg` **inside** the URL branch (lazy import), so local-file runs
  and `--help` don't pay the import cost or trigger side effects.
- `static_ffmpeg.add_paths()` fetches platform ffmpeg binaries over the network on first use and
  caches them in the package directory. Later calls only prepend that directory to `PATH`.
- Why the selectors changed (verified 2026-09-16, details in ADR 006): `worst`/`best` pre-muxed
  selectors now fail with "Requested format is not available". `wv*`/`bv*` resolve for the test
  video to format 269 (H.264 256x144, HLS) and format 605 (VP9 640x360, HLS).
- Without ffmpeg, the HLS download is MPEG-TS bytes in a `.mp4` file (first byte `0x47`). OpenCV
  still decodes it, but yt-dlp warns. With ffmpeg, the file starts with an `ftyp` box. The AC10
  header check guards against losing ffmpeg without noticing.
- URL vs. local file is decided only by `Path(source).is_file()`. A mistyped local path is handed
  to yt-dlp and fails with an "is not a valid URL"-style error, wrapped per AC8.
- **Pitfall from the first implementation:** passing `"wv*"` / `"bv*"` as `quality` "worked", but it
  broke the `Literal` type and produced `downloads/AElGyY97k_0_wv*.mp4`. Don't repeat it (AC1, AC4).

## Open Questions

All resolved:

- Q1: What happens with a local path? **Pass it through unchanged**, so `sample/*.mp4` can validate
  the whole pipeline offline.
- Q2: How do we pick formats without merging? Originally: prefer pre-muxed mp4 via
  `{quality}[ext=mp4]/{quality}`. **Superseded:** pre-muxed formats are no longer offered, so use
  video-only-capable `wv*`/`bv*` selectors ([ADR 006](../../decisions/006-youtube-video-only-formats-and-download-toolchain.md)).
- Q3: How do we handle yt-dlp's JavaScript runtime requirement for YouTube? **Enable `node`**
  explicitly (`deno` is yt-dlp's default but isn't installed).
- Q4: Do we need ffmpeg? For frame reading, no. For clean downloads, yes: **`static-ffmpeg`**,
  activated lazily before URL downloads only.
- Q5: Should the `quality` parameter carry yt-dlp selectors or semantic names? **Semantic names**
  (`worst`/`best`), mapped internally. This keeps file names clean and the type honest.
- Q6: How do we test against real YouTube without making the default suite depend on the network?
  **Mark real-download tests `slow`** (marker registered in `pyproject.toml`). Run them with
  `pytest -m slow`, and skip them with `pytest -m "not slow"`.

## Changelog

- 2026-09-16: The user asked to implement the whole project, with a worst-quality scan download
  followed by a best-quality extraction download. Wrote this spec directly to `ready` (see
  [ADR 004](../../decisions/004-claude-classifier-and-dual-resolution-download.md)) and implemented
  `download()` with local-file passthrough and a yt-dlp URL path using pre-muxed
  `{quality}[ext=mp4]/{quality}` selectors, plus mocked-yt-dlp unit tests.
- 2026-09-16 (commit `9452b23`, undocumented at the time): Added two `@pytest.mark.slow` tests that
  download `https://youtu.be/AElGyY97k_0` at worst and best quality and assert a non-empty `.mp4`.
- 2026-09-16 (commit `f4bfdf8`, undocumented at the time): Real URL downloads failed. The pipeline
  started passing `"wv*"`/`"bv*"` as `quality`. Added `js_runtimes={"node": {}}` and a module-level
  `static_ffmpeg.add_paths()` call, added `static-ffmpeg` to dependencies, and registered the `slow`
  pytest marker. The mocked unit test still asserted the old `worst[ext=mp4]/worst` selector.
- 2026-09-16: Documentation consolidation for the planned rebuild
  ([ADR 007](../../decisions/007-documentation-consolidation-for-rebuild.md)). Recorded the
  undocumented changes above as [ADR 006](../../decisions/006-youtube-video-only-formats-and-download-toolchain.md).
  Rewrote the ACs to the working behavior plus these fixes:
  semantic `quality` mapped to `wv*`/`bv*` internally (AC1, AC3);
  no `*` in file names (AC4);
  lazy, URL-only `static_ffmpeg.add_paths()` (AC6);
  offline tests for both selectors and for import-time side effects (AC9);
  and a stronger slow test (AC10).
  Reset status to `ready` with unchecked ACs because the implementation will be erased and rebuilt.
- 2026-09-16: "Implement the project according to the docs in it. Commit each feature
  individually." Rebuild step 2 of [ADR 007](../../decisions/007-documentation-consolidation-for-rebuild.md).
  Added `src/extract_memes/downloader.py`: local-file passthrough, then lazy `yt_dlp` and
  `static_ffmpeg` imports, `dest_dir` creation, `static_ffmpeg.add_paths()`, and a `YoutubeDL`
  call that maps `worst`/`best` to `wv*[ext=mp4]/wv*`/`bv*[ext=mp4]/bv*` via a module-level
  `FORMAT_SELECTORS` dict. Any yt-dlp error is wrapped in a chained `RuntimeError` naming the
  source and quality. Declared `yt-dlp` and `static-ffmpeg` in `pyproject.toml`. Added
  `tests/test_downloader.py`: offline tests with `yt_dlp.YoutubeDL` and `static_ffmpeg.add_paths`
  mocked (AC9), plus `slow` tests that download the test video once per module into a temporary
  directory (AC10). The `slow` tests import `cv2` inside the test function, so the offline tests
  don't need OpenCV before frame-extraction declares it. Verified: offline and `slow` tests pass;
  a real download writes `AElGyY97k_0_worst.mp4` (152831 bytes, `ftyp` header) with no yt-dlp
  warnings; a mistyped local path raises `RuntimeError` chained from `DownloadError`. All ACs
  checked; status `implemented`.
- 2026-09-18: The user asked for a progress bar during yt-dlp downloads — previously explicitly
  out of scope (`noprogress=True`, no reporting). Added AC11: a `tqdm` bar per download, driven by
  a new `_progress_hook` via yt-dlp's `progress_hooks` option, matching the `tqdm`-per-stage
  convention already used for scanning and extraction rather than yt-dlp's own console output.
  Removed the stale "no progress reporting" line from Out of Scope.
  - **Downloader:** `_progress_hook(bar)` in `src/extract_memes/downloader.py`, wired into
    `download`'s yt-dlp options as `progress_hooks=[hook]`; `desc=f"Downloading ({quality})"`.
  - **Tests:** `test_url_download_options` asserts exactly one callable in `progress_hooks`; three
    new direct tests exercise `_progress_hook` against a real `tqdm` instance (`"downloading"`
    events, the `total_bytes_estimate` fallback, topping off on `"finished"`, and a `"finished"`
    event with nothing known yet leaving the bar untouched).
  - **Verified:** `pytest -m "not slow"` — 183 passed. All ACs checked; status remains
    `implemented`.
- 2026-09-18: The user asked whether yt-dlp downloads could go through a proxy, in the context of
  reaching a LAN SOCKS5 proxy ([ADR 017](../../decisions/017-macos-local-network-proxy-relay.md)).
  Added AC12: `download(..., proxy: str | None = None)` passes `proxy` straight through as yt-dlp's
  `proxy` option on the URL path only; `pipeline.run` gained a matching `proxy` parameter forwarded
  to both the `"worst"` and `"best"` downloads; the CLI gained `--proxy`, falling back to the
  `EXTRACT_MEMES_PROXY` env var (same pattern as the Telegram token/chat-id flags).
  - **Downloader:** `proxy` param on `download`; `options["proxy"] = proxy` set only when truthy.
  - **Pipeline:** `run(..., proxy: str | None = None)`, forwarded to both `download` calls.
  - **CLI:** `--proxy` argument in `build_parser`; `main` resolves it as
    `args.proxy or os.environ.get("EXTRACT_MEMES_PROXY")` and passes it to `pipeline.run`.
  - **Tests:** offline tests in `test_downloader.py` (proxy passed through on the URL path, omitted
    when unset, ignored for a local-file source); `test_pipeline.py` (`proxy` forwarded to both
    downloads via a `download` spy); `test_cli.py` (flag reaches the pipeline, env-var fallback,
    flag overrides env var, and the two existing call-signature tests updated for the new kwarg).
  - **Verified:** `pytest -m "not slow"` — 200 passed. All ACs checked; status remains
    `implemented`.
