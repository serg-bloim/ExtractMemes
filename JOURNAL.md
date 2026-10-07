# Project Journal

Flat index of requests and actions, one line per entry, most recent last. Detail lives in the
linked spec's Changelog or ADR — see CLAUDE.md's "Project Journal" section.

---

- 2026-09-16: Described the meme-extraction pipeline and added it to CLAUDE.md's Project
  Overview.
- 2026-09-16: Planned the milestone rollout (walking-skeleton: download → extract → save first,
  classifier deferred) — [ADR 002](decisions/002-meme-extraction-pipeline-rollout-plan.md).
- 2026-09-16: Deleted the overly-broad meme-extraction-pipeline spec (was the whole project
  goal, not one requirement); updated ADR 002 and CLAUDE.md accordingly —
  [ADR 002](decisions/002-meme-extraction-pipeline-rollout-plan.md).
- 2026-09-16: Created, refined, and implemented the M0 project setup spec —
  [specs/features/project-setup.md](specs/features/project-setup.md).
- 2026-09-16: Switched JOURNAL.md to a one-line index; moved per-change detail into each spec's
  new Changelog section — [ADR 003](decisions/003-journal-changelog-split.md).
- 2026-09-16: Rebuild step 1: registered the `slow` pytest marker and an import side-effect test;
  project setup is `in-progress` until the feature modules exist —
  [specs/features/project-setup.md](specs/features/project-setup.md).
- 2026-09-16: Rebuild step 2: implemented `download()` with local passthrough, `wv*`/`bv*`
  selectors behind `worst`/`best`, and lazy ffmpeg setup —
  [specs/features/video-download.md](specs/features/video-download.md).
- 2026-09-16: Rebuild step 3: implemented `sample_frames` and `frame_at` with OpenCV —
  [specs/features/frame-extraction.md](specs/features/frame-extraction.md).
- 2026-09-16: Rebuild step 4: implemented `ClaudeCliClassifier` with the verbatim v3 rubric and
  strict error handling — [specs/features/meme-classifier.md](specs/features/meme-classifier.md).
- 2026-09-16: Rebuild step 5: implemented `pipeline.run`, run-name derivation, and the full
  `extract-memes` CLI — [specs/features/extraction-pipeline.md](specs/features/extraction-pipeline.md).
- 2026-09-16: Completed project setup: full dependency set and all six test modules, verified with
  a fresh-virtualenv install — [specs/features/project-setup.md](specs/features/project-setup.md).
- 2026-09-16: Rebuild step 6: recreated `run_real_video.py` and `playground/playground.py` —
  [specs/features/dev-harness.md](specs/features/dev-harness.md).
- 2026-09-16: Rebuild smoke check passed: the real run on `sample/short.mp4` flagged exactly the
  two known meme cards (10.56 s, 28.80 s) —
  [specs/features/extraction-pipeline.md](specs/features/extraction-pipeline.md).
- 2026-09-16: Proposed iteration 2, a hand-built image heuristic as the default classifier with the
  Claude classifier kept as the rebuild baseline, and defined iteration specs —
  [ADR 008](decisions/008-heuristic-classifier-iteration.md).
- 2026-09-16: Drafted the heuristic classifier spec (band and texture margin scores, `--classifier`
  switch) — [specs/features/heuristic-classifier.md](specs/features/heuristic-classifier.md).
- 2026-09-16: Moved the labeled frames from `.runtime/experiment/` to `data/labeled_dataset/` —
  [specs/features/heuristic-classifier.md](specs/features/heuristic-classifier.md).
- 2026-09-16: Implemented iteration 2: `HeuristicClassifier` is the default classifier, with
  `--classifier claude` still available —
  [specs/features/heuristic-classifier.md](specs/features/heuristic-classifier.md).
- 2026-09-17: Proposed iteration 3: scan frames in memory, and separate `high-res/` and opt-in
  `low-res/` output folders — [ADR 009](decisions/009-in-memory-scan-and-resolution-folders.md).
- 2026-09-17: Drafted the in-memory scan frames spec (`--save-frames`, temporary files for the
  Claude classifier) — [specs/features/in-memory-frames.md](specs/features/in-memory-frames.md).
- 2026-09-17: Drafted the resolution output folders spec (`high-res/`, `--save-low-res`) —
  [specs/features/resolution-output-folders.md](specs/features/resolution-output-folders.md).
- 2026-09-17: Implemented iteration 3: frames in memory, `high-res/` and `--save-low-res` output
  folders —
  [specs/features/in-memory-frames.md](specs/features/in-memory-frames.md),
  [specs/features/resolution-output-folders.md](specs/features/resolution-output-folders.md).
- 2026-09-17: Added the missing iteration 3 tests, fixed the CLI description, and corrected
  overstated changelog claims —
  [specs/features/in-memory-frames.md](specs/features/in-memory-frames.md),
  [specs/features/resolution-output-folders.md](specs/features/resolution-output-folders.md).
- 2026-09-17: Added `frames_from` for reading a run of consecutive frames from one open-and-seek — [specs/features/frame-extraction.md](specs/features/frame-extraction.md).
- 2026-09-17: Extraction now saves a ±1s batch of re-classified full-quality frames per meme, grouped in `high-res/meme_<n>/` — [specs/features/extraction-pipeline.md](specs/features/extraction-pipeline.md).
- 2026-09-17: Each meme batch is combined into one less distorted image in `clean/meme_<n>.png` with a temporal trimmed mean — [specs/features/batch-cleaning.md](specs/features/batch-cleaning.md).
- 2026-09-17: Added `darkest` and `darkest_mean` cleaning methods, which exploit that the glitch bands only brighten — [specs/features/batch-cleaning.md](specs/features/batch-cleaning.md).
- 2026-09-17: Added the `clean_rows` cleaning method, which uses the letterbox bars to tell damaged rows from clean ones — [specs/features/batch-cleaning.md](specs/features/batch-cleaning.md).
- 2026-09-17: Ran the full video with every cleaning method (93 memes in `.runtime/full_experiment/`) and made `clean_rows` the default — [decisions/011-clean-rows-as-the-default.md](decisions/011-clean-rows-as-the-default.md).
- 2026-09-17: Keeping each meme's full-quality frames is now opt-in (`--save-high-res`); a default run writes only the cleaned images — [specs/features/batch-cleaning.md](specs/features/batch-cleaning.md).
- 2026-09-17: Added `--save-timecodes`, which writes each meme's start as a YouTube timecode to `timecodes.txt`, with an optional `--timecode-offset` — [specs/features/meme-timecodes.md](specs/features/meme-timecodes.md).
- 2026-09-17: Added `--no-images`, a timecodes-only run that stops after the scan and skips the best-quality download — [specs/features/no-images.md](specs/features/no-images.md).
- 2026-09-17: Added a `Dockerfile`/`.dockerignore` to package the pipeline as a runnable image — [decisions/012-docker-image.md](decisions/012-docker-image.md).
- 2026-09-17: Added a GitHub Actions workflow that builds and pushes the Docker image to GHCR on each `v*` tag — [decisions/013-github-actions-docker-publish.md](decisions/013-github-actions-docker-publish.md).
- 2026-09-18: Added `--upload-to telegram`, which uploads every saved meme to a Telegram chat as a final pipeline stage — [specs/features/meme-upload.md](specs/features/meme-upload.md), [decisions/014-telegram-upload-as-pipeline-stage.md](decisions/014-telegram-upload-as-pipeline-stage.md).
- 2026-09-18: Redesigned Telegram delivery, after live testing, to post the source link once and the memes as chunked reply albums instead of one message per image — [specs/features/meme-upload.md](specs/features/meme-upload.md), [decisions/015-telegram-album-and-link-delivery.md](decisions/015-telegram-album-and-link-delivery.md).
- 2026-09-18: Added a `tqdm` progress bar for yt-dlp downloads, driven by `progress_hooks` — [specs/features/video-download.md](specs/features/video-download.md).
- 2026-09-18: Added a manually-triggered GitHub Actions workflow that checks a playlist for the oldest unprocessed video and runs the pipeline on it — [specs/features/playlist-watch.md](specs/features/playlist-watch.md), [decisions/016-scheduled-playlist-watcher.md](decisions/016-scheduled-playlist-watcher.md).
- 2026-09-18: Split the check-new-video workflow's install into a light `yt-dlp`-only step for checking and a full dependency install deferred to only when a video is actually found — [specs/features/playlist-watch.md](specs/features/playlist-watch.md).
- 2026-09-18: Diagnosed Python failing to reach the LAN SOCKS proxy that `curl` could reach — macOS Local Network privacy denying the ad-hoc-signed Homebrew interpreter — and added `tools/lan_proxy_relay.py` as the workaround — [decisions/017-macos-local-network-proxy-relay.md](decisions/017-macos-local-network-proxy-relay.md).
- 2026-09-18: Found the Local Network permission *is* grantable to an ad-hoc-signed interpreter (via a LaunchServices-launched `.app` wrapper); repointed the proxy scripts straight at the LAN address and demoted the relay to a fallback — [decisions/017-macos-local-network-proxy-relay.md](decisions/017-macos-local-network-proxy-relay.md).
- 2026-09-18: Added a `--proxy` CLI option (env fallback `EXTRACT_MEMES_PROXY`) so yt-dlp downloads can go through a proxy, e.g. the LAN SOCKS5 relay — [specs/features/video-download.md](specs/features/video-download.md).
- 2026-09-18: Moved `processed_vids.txt` off `main` onto a separate orphan `data` branch, checked out side by side in `check-new-video.yml`, so bot bookkeeping commits no longer interleave with code history — [specs/features/playlist-watch.md](specs/features/playlist-watch.md), [decisions/018-processed-videos-on-orphan-data-branch.md](decisions/018-processed-videos-on-orphan-data-branch.md).
- 2026-09-18: Added proxy support to `playlist_watch find` (`--proxy`/`EXTRACT_MEMES_PROXY`, same env var as `extract-memes`) and a job-level `secrets.YT_DLP_PROXY` in `check-new-video.yml`, so both yt-dlp call sites in the workflow go through the proxy — [specs/features/playlist-watch.md](specs/features/playlist-watch.md).
- 2026-09-19: Built partial best-quality downloads, timed them against a real 63-minute video, found them ~6x slower than fetching the whole file, and reverted — the research is kept — [specs/features/partial-high-res-download.md](specs/features/partial-high-res-download.md), [decisions/020-whole-video-download-stands.md](decisions/020-whole-video-download-stands.md).
- 2026-09-19: Added `--send-timecodes-to telegram`/`--timecode-chat-id`, delivering a run's timecodes to a second Telegram chat (same bot as image uploads) as a source-link message plus a reply — [specs/features/timecode-channel.md](specs/features/timecode-channel.md).
- 2026-10-04: The Telegram parent post now carries the source video's thumbnail and title, with title-text and bare-link fallbacks — [specs/features/meme-upload.md](specs/features/meme-upload.md).
- 2026-10-04: Telegram albums now post as comments under the parent post when the channel has a linked discussion group, falling back to channel replies — [specs/features/meme-upload.md](specs/features/meme-upload.md).
- 2026-10-04: The check-new-video workflow now uses the optional `LOOKBACK_COUNT` repo variable as `--count`, keeping the default when unset — [specs/features/playlist-watch.md](specs/features/playlist-watch.md).
- 2026-10-04: The check-new-video workflow now reads `TELEGRAM_CHAT_ID` from repo variables instead of secrets — [specs/features/playlist-watch.md](specs/features/playlist-watch.md).
- 2026-10-04: The check-new-video workflow can now save each video's low-res and high-res images to the data branch under its video id, enabled by the `SAVE_IMAGES` repo variable — [specs/features/playlist-watch.md](specs/features/playlist-watch.md).
- 2026-10-04: Added `--progress-delta SECONDS`, throttling the yt-dlp and tqdm progress updates — [specs/features/extraction-pipeline.md](specs/features/extraction-pipeline.md).
- 2026-10-05: Scan-frame timestamps now come from each frame's own presentation time, fixing low-res/high-res drift on uneven-rate videos — [specs/features/frame-extraction.md](specs/features/frame-extraction.md).
- 2026-10-05: Drafted a spec to merge flagged frames within a configurable window (`--merge-window`, 1 s default) into one meme — [specs/features/meme-merge-window.md](specs/features/meme-merge-window.md).
- 2026-10-05: Added `--merge-window SECONDS` (1 s default), merging flagged frames within the window of a meme's first flagged frame into one meme — [specs/features/meme-merge-window.md](specs/features/meme-merge-window.md).
- 2026-10-05: Added playground/scan_playground.py for scan-only runs (no extraction) — [specs/features/dev-harness.md](specs/features/dev-harness.md).
- 2026-10-05: Drafted a spec to make the heuristic classifier decide on band only, dropping the texture test — [specs/features/heuristic-band-only.md](specs/features/heuristic-band-only.md).
- 2026-10-05: The heuristic classifier now decides on the band score alone, dropping the texture test (541 vs 445 flagged frames on the full video) — [specs/features/heuristic-band-only.md](specs/features/heuristic-band-only.md).
- 2026-10-05: The default scan rate is now 3 fps (CLI and `pipeline.run`), which finds cards that 2 fps falls between — [specs/features/extraction-pipeline.md](specs/features/extraction-pipeline.md).
- 2026-10-05: Replaced the `LOOKBACK_COUNT` count with a `--since` date (workflow variable `SINCE`) — [specs/features/playlist-watch.md](specs/features/playlist-watch.md).
- 2026-10-05: The workflow now has separate `SAVE_LOW_RES`/`SAVE_HIGH_RES`/`SAVE_CLEAN`/`SAVE_FRAMES` variables and writes its run directory straight into the data branch — [specs/features/playlist-watch.md](specs/features/playlist-watch.md).
- 2026-10-05: The workflow's run directories are now grouped under `runs/` on the data branch — [specs/features/playlist-watch.md](specs/features/playlist-watch.md).
- 2026-10-05: Added playground/ytdlp_playground.py, which prints every yt-dlp format of a video — [specs/features/dev-harness.md](specs/features/dev-harness.md).
- 2026-10-05: Drafted a spec to stop downloading AV1, which OpenCV can't decode on the GitHub runner — [specs/features/decodable-codec-download.md](specs/features/decodable-codec-download.md).
- 2026-10-05: Settled the AV1 spec: exclude only AV1, still download it when it is the only codec; status `ready`, not implemented — [specs/features/decodable-codec-download.md](specs/features/decodable-codec-download.md).
- 2026-10-05: Drafted a spec to fail the run when a video opens but no frames can be decoded — [specs/features/fail-on-undecodable-video.md](specs/features/fail-on-undecodable-video.md).
- 2026-10-05: Settled the fail-on-undecodable-video spec (first bad window fails; no memes or no saved images is not an error); status `ready` — [specs/features/fail-on-undecodable-video.md](specs/features/fail-on-undecodable-video.md).
- 2026-10-05: A run now fails when a video opens but no frame can be decoded, instead of finishing with no memes — [specs/features/fail-on-undecodable-video.md](specs/features/fail-on-undecodable-video.md).
- 2026-10-05: Specified a data-branch cache of video upload dates so `find` stops re-fetching them every run; status `ready`, not implemented — [specs/features/playlist-watch.md](specs/features/playlist-watch.md).
- 2026-10-05: `find` now caches each video's upload date on the data branch, saving after every fetched date so a cancelled run keeps them — [specs/features/playlist-watch.md](specs/features/playlist-watch.md).
- 2026-10-05: The playlist fetch now enables the Node.js runtime, which stops yt-dlp's JavaScript-runtime warning — [specs/features/playlist-watch.md](specs/features/playlist-watch.md).
- 2026-10-06: Downloads now skip AV1 formats unless AV1 is all a video offers, so OpenCV can decode them on the GitHub runner — [specs/features/decodable-codec-download.md](specs/features/decodable-codec-download.md).
- 2026-10-07: Drafted specs for a labeled video dataset (video reference plus marked timestamps in `data/datasets/*.yaml`) — [specs/features/labeled-video-dataset.md](specs/features/labeled-video-dataset.md).
- 2026-10-07: Drafted a spec for a local web page to label a video's memes frame by frame — [specs/features/frame-labeler.md](specs/features/frame-labeler.md).
- 2026-10-07: Implemented the labeled-video dataset format and loader (`tools/labeling/dataset.py`) — [specs/features/labeled-video-dataset.md](specs/features/labeled-video-dataset.md).
- 2026-10-07: Built the frame labeler (local server, scrollable strip, classifier scores and filters); page UI not yet verified by hand — [specs/features/frame-labeler.md](specs/features/frame-labeler.md).
- 2026-10-07: The labeler can select several strip rows (shift+click range, Cmd/Ctrl+click toggle) and mark or unmark them in one request — [specs/features/frame-labeler.md](specs/features/frame-labeler.md).
- 2026-10-07: Datasets and the labeler gained an explicit "not a meme" label (`not_memes`, key X) for hard negatives — [specs/features/frame-labeler.md](specs/features/frame-labeler.md).
- 2026-10-07: Moved the labeler server to Flask and added `labeler.sh`, a dev server that reloads on source edits — [specs/features/frame-labeler.md](specs/features/frame-labeler.md).
- 2026-10-07: Added `labeler-run.sh`, a one-command start of the labeler dev server with the usual settings — [specs/features/frame-labeler.md](specs/features/frame-labeler.md).
- 2026-10-07: The labeler page gained an "Open video" modal: paste a URL/id, see the video's details and formats, load the chosen format — [specs/features/frame-labeler.md](specs/features/frame-labeler.md).
- 2026-10-07: The open-video modal preselects a format by fps ≥ 25, then smallest resolution, then not AV1 — [specs/features/frame-labeler.md](specs/features/frame-labeler.md).
- 2026-10-07: The open-video modal has a dropdown of processed videos (those with a dataset) — [specs/features/frame-labeler.md](specs/features/frame-labeler.md).
- 2026-10-07: Esc in the labeler now deselects every frame, not only the range — [specs/features/frame-labeler.md](specs/features/frame-labeler.md).
- 2026-10-07: The labeler has a histogram view of the classifier criteria's scores (all frames, or only the selection), stacked by human label — [specs/features/frame-labeler.md](specs/features/frame-labeler.md).
- 2026-10-07: Dragging a range on the labeler's histogram filters the strip to frames in that range — [specs/features/frame-labeler.md](specs/features/frame-labeler.md).
- 2026-10-07: The labeler can copy the selected frame(s)' locator (video id, format id, timestamp, index) to the clipboard — [specs/features/frame-labeler.md](specs/features/frame-labeler.md).
- 2026-10-07: Each filter line in the labeler has its own reset button — [specs/features/frame-labeler.md](specs/features/frame-labeler.md).
- 2026-10-07: The labeler's histogram now follows the strip's filters (the charted metric's own range fades bars instead of removing them) — [specs/features/frame-labeler.md](specs/features/frame-labeler.md).
- 2026-10-07: The labeler's histogram zooms with the trackpad two-finger scroll (around the pointer; horizontal scroll pans; "Reset zoom") — [specs/features/frame-labeler.md](specs/features/frame-labeler.md).
- 2026-10-07: The labeler histogram's dimmed out-of-range bars keep their meme / not-a-meme / unlabeled colours — [specs/features/frame-labeler.md](specs/features/frame-labeler.md).
- 2026-10-07: Labeler criteria now depend on the production classifier (shared margin geometry, threshold read from it, cache invalidated when its source changes) — [specs/features/frame-labeler.md](specs/features/frame-labeler.md).
- 2026-10-07: Moved all classifier criteria into `extract_memes.criteria` (one auto-discovered module each) with a rule layer (`Condition`/`AllOf`/`AnyOf`/`RuleClassifier`); the labeler reuses them with no copies, and a new criterion file shows up in it — [specs/features/classifier-criteria.md](specs/features/classifier-criteria.md).
- 2026-10-07: Fixed "could not load frame N" on the first frames of H.264 videos whose seek can't reach them — [specs/features/frame-labeler.md](specs/features/frame-labeler.md).
