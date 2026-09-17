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
