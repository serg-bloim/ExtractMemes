# 006 — YouTube Downloads: Video-Only Formats, Node.js JS Runtime, Bundled ffmpeg

**Date:** 2026-09-16
**Status:** Accepted. Recorded after the fact during the documentation consolidation
([ADR 007](007-documentation-consolidation-for-rebuild.md)). The change itself landed in commit
`f4bfdf8` ("upd") with no spec or ADR update.

---

## Context

ADR 004 and the video-download spec said the downloader picks a **single pre-muxed format**
(video+audio already combined) with the selector `f"{quality}[ext=mp4]/{quality}"`, where
`quality` is `worst` or `best`. ADR 002 also said the project needs **no system `ffmpeg`**.

The first end-to-end runs only used local files (`sample/short.mp4`), so the URL path was covered
only by tests that mocked yt-dlp. When the pipeline was first run against a real YouTube URL
(`https://youtu.be/AElGyY97k_0`, the project's permanent test video: 12.08s, 25 fps, 360p at most),
three problems appeared. They were fixed in code without being written down. We re-checked them
on 2026-09-16 with yt-dlp 2026.8.19:

1. **Pre-muxed formats are gone.** Both `worst[ext=mp4]/worst` and `best[ext=mp4]/best` fail with
   `ERROR: [youtube] AElGyY97k_0: Requested format is not available`. YouTube now serves this
   video only as separate video and audio streams (HLS / DASH).
2. **yt-dlp needs a JavaScript runtime for YouTube.** With no runtime configured, yt-dlp warns:
   `No supported JavaScript runtime could be found. Only deno is enabled by default ... YouTube
   extraction without a JS runtime has been deprecated, and some formats may be missing`. `deno`
   isn't installed on this machine, but `node` (v26.8.2) is.
3. **HLS downloads need ffmpeg to become real MP4 files.** The formats yt-dlp picks are delivered
   over `m3u8_native` (HLS). Without ffmpeg, yt-dlp warns `Possible MPEG-TS in MP4 container or
   malformed AAC timestamps. Install ffmpeg to fix this automatically`, and the saved `.mp4` is
   really an MPEG-TS stream (the file starts with the TS sync byte `0x47`). OpenCV still decodes
   all 302 frames of that file, so ffmpeg isn't strictly needed for frame extraction. With ffmpeg
   on `PATH`, yt-dlp remuxes the file, and it starts with a real MP4 `ftyp` box.

What the selectors resolve to for the test video:

| Selector               | Result                                                         |
|------------------------|----------------------------------------------------------------|
| `worst[ext=mp4]/worst` | Error: requested format is not available                       |
| `best[ext=mp4]/best`   | Error: requested format is not available                       |
| `wv*[ext=mp4]/wv*`     | Format `269`: mp4, `avc1.4D400C`, **256x144**, no audio, HLS   |
| `bv*[ext=mp4]/bv*`     | Format `605`: mp4, `vp09.00.21.08`, **640x360**, no audio, HLS |

## Decision

1. **Use video-only-capable selectors.** Internally, quality `worst` maps to `wv*[ext=mp4]/wv*` and
   quality `best` maps to `bv*[ext=mp4]/bv*`. (`wv*`/`bv*` mean "worst/best format that contains
   video, with or without audio".) The pipeline only reads frames, so audio isn't needed. Nothing
   is merged, and no audio stream is downloaded.
2. **Enable Node.js as yt-dlp's JS runtime** with the option `js_runtimes={"node": {}}`.
3. **Provide ffmpeg through the `static-ffmpeg` pip package** (`static_ffmpeg.add_paths()`), so
   yt-dlp's post-download fixup can remux HLS output into a real MP4. No manual system install is
   needed.
4. **Keep the semantic quality names in the API and in filenames.** The first fix passed raw
   selectors (`"wv*"`, `"bv*"`) through `download()`'s `quality` argument. That broke the
   `Literal["worst", "best"]` type and put a literal `*` in file names
   (`downloads/AElGyY97k_0_bv*.mp4`). In the rebuild, `download()` accepts only `worst`/`best` and
   maps them to selectors internally. Files are named `<video id>_worst.<ext>` and
   `<video id>_best.<ext>`.
5. **Call `static_ffmpeg.add_paths()` only on the URL path.** The first fix called it at module
   import time, which fetched or located the ffmpeg binaries and changed `PATH` even for
   `extract-memes --help`, local-file runs, and offline unit tests. In the rebuild it runs only
   right before a real yt-dlp download.

## Options Considered

### Option A: Keep pre-muxed `worst`/`best` (ADR 004 as written)

**Rejected:** it no longer works. YouTube doesn't offer those formats for the test video.

### Option B: `bv*+ba` (best video + best audio, merged)

**Rejected:** merging needs ffmpeg, and it downloads audio the pipeline never uses.

### Option C: Video-only `wv*` / `bv*` (chosen)

The smallest change that works. The scan copy stays tiny (144p), and there's nothing to merge.

### Option D: Don't use ffmpeg; accept MPEG-TS bytes in a `.mp4` file

**Viable fallback, not chosen:** OpenCV reads the file fine. But the file is mislabeled, yt-dlp
warns on every download, and other tools may not open it. Worth remembering if `static-ffmpeg`
ever becomes a problem.

### Option E: Require ffmpeg via Homebrew or a system package

**Rejected:** it adds a manual setup step. `static-ffmpeg` installs with `pip install -e .`.

### Option F: Use `deno` (yt-dlp's default JS runtime)

**Rejected for now:** `node` is already installed and works. Either runtime satisfies yt-dlp.

## Consequences

**Positive:**
- Real YouTube URLs download again at both quality tiers.
- The two tiers really differ in resolution (144p scan copy, 360p+ extraction copy), which is
  what ADR 004's two-pass design needs.
- Downloads are real MP4 files, and nothing extra needs to be installed by hand.

**Negative / costs:**
- New runtime prerequisite: **Node.js on `PATH`** for URL sources. Local-file sources don't need it.
- `static-ffmpeg` downloads platform ffmpeg binaries over the network the first time it's used,
  and caches them in its package directory.
- YouTube's format and anti-bot behavior keeps changing. The `slow`-marked real-download tests are
  how we'll notice the next break.
- The best-quality file may use a different codec than the scan file (VP9 vs. H.264 here). The
  OpenCV build in use (`opencv-python-headless` 5.0.0.93) decodes and seeks both accurately. See
  the frame-extraction spec.

## References

- [ADR 002](002-meme-extraction-pipeline-rollout-plan.md): its "no system ffmpeg" assumption still
  holds for frame reading, but not for downloads.
- [ADR 004](004-claude-classifier-and-dual-resolution-download.md): its pre-muxed format selection
  is superseded.
- [ADR 007](007-documentation-consolidation-for-rebuild.md): the consolidation that recorded this.
- `specs/features/video-download.md`
