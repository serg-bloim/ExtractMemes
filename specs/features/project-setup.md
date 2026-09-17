---
title: "Project Setup"
status: implemented
created: 2026-09-16
updated: 2026-09-16
author: ""
depends-on: []
---

# Project Setup

## Problem Statement

ExtractMemes needs a code foundation before any pipeline stage can be built: declared
dependencies, an installable source package, a CLI entrypoint, a test setup that separates offline
tests from slow real-network ones, and ignore rules. The ignore rules keep large generated files
(downloaded videos, thousands of sampled frames, local video fixtures) out of git. Without this,
every later milestone would re-decide where code and tests live and how the tool runs. This spec
defines that minimal, installable, tested skeleton. It's the first thing built in the rebuild.

## User Story

**Primary:**
As the developer of ExtractMemes, I want a minimal project skeleton that installs, runs, and has
a working test setup, so that each later milestone can add its module and its tests in an agreed
place without deciding the project structure again.

## Acceptance Criteria

- [x] AC1: A `pyproject.toml` at the project root declares:
      - project `extract-memes`, version `0.1.0`, `requires-python = ">=3.14"`;
      - build backend `setuptools.build_meta` (`setuptools>=68`), with packages found under
        `src`;
      - a `dev` optional dependency group containing `pytest`;
      - runtime `dependencies` holding exactly the packages that the feature specs declare as
        they're implemented (the full set is in Technical Notes).

      `pip install -e ".[dev]"` succeeds in a fresh Python 3.14 virtualenv. There is no
      `requirements.txt`.
- [x] AC2: The package lives at `src/extract_memes/`, and `__init__.py` has a one-line docstring.
      After the editable install, `python -c "import extract_memes"` succeeds from any directory.
      Importing any module of the package has no side effects: no network access, no `PATH`
      changes, no files written.
- [x] AC3: `pyproject.toml` declares the console script `extract-memes = "extract_memes.__main__:main"`.
      After the install, both `extract-memes --help` and `python -m extract_memes --help` exit 0
      and print usage text that describes the tool's purpose. There is no `main.py` at the project
      root.
- [x] AC4: A top-level `tests/` folder holds one test module per source module
      (`test_package.py`, `test_cli.py`, `test_downloader.py`, `test_frame_extractor.py`,
      `test_classifier.py`, `test_pipeline.py`). `pyproject.toml` registers a `slow` marker under
      `[tool.pytest.ini_options]`:
      `markers = ["slow: marks tests as slow (deselect with '-m \"not slow\"')"]`.
      There are three test tiers:
      1. Offline unit tests, which always run.
      2. Fixture tests that need `sample/*.mp4`, skipped with a reason when the fixture is absent.
      3. `slow` tests that need the network (real YouTube). They're selected by default, and
         excluded with `-m "not slow"`.

      `pytest -m "not slow"` passes with no network and no `claude` binary on `PATH`.
- [x] AC5: `.gitignore` contains exactly these entries: `.venv/`, `.idea/`, `__pycache__/`,
      `*.py[cod]`, `.pytest_cache/`, `*.egg-info/`, `downloads/`, `.runtime/`, `/sample/`. After
      installing, running the tool and tests, and placing dummy files in `downloads/`,
      `.runtime/x/`, and `sample/`, `git status` shows none of them as untracked.
- [x] AC6: The "Code Conventions" section of `CLAUDE.md` covers:
      - the language and version (Python 3.14);
      - where dependencies are declared (`pyproject.toml`) and how to install them;
      - how to run the tool;
      - how to run the tests, including the `slow` tier;
      - the external runtime prerequisites (see Technical Notes);
      - the convention that each module gets matching tests under `tests/`.
- [x] AC7: The "Directory Structure" tree in `CLAUDE.md` shows `pyproject.toml`,
      `src/extract_memes/` (with its modules), `tests/`, `playground/`, `run_real_video.py`,
      `sample/`, `downloads/`, and `.runtime/<run-name>/{frames,saved}/`.

## Out of Scope

- Any pipeline behavior. Each feature spec adds its own module, tests, and dependencies.
- Placeholder modules for later stages.
- Linter or formatter setup, CI, a lock file with pinned versions, or publishing to PyPI.
- Committing video fixtures (`sample/` is gitignored; `full.mp4` alone is ~95 MB).

## Technical Notes

- A virtualenv already exists at `.venv/`, created by PyCharm, on CPython 3.14.7.
- The build backend is `setuptools`. It's needed only to install the package, not at runtime.
  With the package installed in editable mode, pytest imports it without extra path configuration.
- The CLI uses the standard library's `argparse`.
- **Full runtime dependency set once every feature spec is implemented** (no version pins; these
  versions were known to work together on 2026-09-16):

  | Package | Introduced by | Known-good version |
  |---|---|---|
  | `yt-dlp` | video-download | 2026.8.19 |
  | `static-ffmpeg` | video-download | 3.0 |
  | `opencv-python-headless` | frame-extraction | 5.0.0.93 |
  | `numpy` | frame-extraction | 2.5.3 |
  | `tqdm` | extraction-pipeline | 4.70.1 |
  | `pytest` (dev) | project-setup | 9.1.1 |

- **External runtime prerequisites** (not pip-installable, not checked at install time):
  - `claude` (Claude Code CLI), installed, authenticated, and on `PATH`. It's needed for real
    classification only. Known-good version 2.1.267. See meme-classifier.
  - Node.js on `PATH`, needed for YouTube URL sources only (yt-dlp's JS runtime). Known-good
    v26.8.2. See video-download and ADR 006.
  - **Not** needed: a system `ffmpeg` (OpenCV bundles its own decoder, and `static-ffmpeg`
    supplies ffmpeg to yt-dlp), and `deno`.
- **Local fixtures in `sample/` (gitignored, so they must be supplied by hand):**

  | File | Properties | Used by |
  |---|---|---|
  | `short.mp4` | 78.56 s, 256x144, 25 fps, H.264, 1964 frames. Contains 2 glitch meme cards (≈10.56 s, ≈28.80 s) and portrait-video look-alikes (≈31–38 s blurred side fill, ≈73–76 s black bars). | frame-extraction and pipeline tests, playground |
  | `full.mp4` | 3763.8 s (~62.7 min), 256x144, 25 fps, H.264, 94095 frames. Apparent source of the labeled evaluation frames. | playground `test_full_video_run` only |
  | `short2.mp4` | 64.44 s, 640x360, 25 fps. Reports 1611 frames but decodes 1501. | ad-hoc checks only |
  | `short3.mp4` | 16.04 s, 640x360, 25 fps, reports 401 frames | ad-hoc checks only |
  | `quick_frame_9-32.png` | 256x144 positive example of a glitch meme card | reference only |

- **Permanent network test video:** `https://youtu.be/AElGyY97k_0` (12.08 s, 25 fps, 302 frames;
  worst tier 256x144 H.264, best tier 640x360 VP9). It's used by `slow` tests and
  `run_real_video.py`.

## Open Questions

All resolved:

- Q1: Placeholder modules for later stages? **No.** Each milestone adds its own module when it's
  built, so there are no empty files.
- Q2: Default locations for downloaded videos and output? Originally **`downloads/` and `output/`**.
  **Updated by ADR 005:** output moved to `.runtime/<run-name>/{frames,saved}/`, and `output/` no
  longer exists. `downloads/` stays the CLI default.
- Q3: Gitignore `.idea/` or commit it? **Gitignore it entirely.**
- Q4: Supported Python versions? **3.14 only for now**, matching `.venv`.
- Q5: Linter/formatter? **Deferred.** Revisit once there's meaningful code.
- Q6: Package layout? **`src/` layout** (`src/extract_memes/`).
- Q7: Where are dependencies declared? **`pyproject.toml` only**, with dev tools in a `dev` optional
  group. No `requirements.txt`.
- Q8: How is the tool run? **As a console command** (`extract-memes`), plus `python -m extract_memes`.
  No root `main.py`.
- Q9: Set up tests in M0 or later? **In M0.** A top-level `tests/` folder with pytest; M0's
  acceptance criteria are the first tests.
- Q10: Commit the video fixtures? **No.** `/sample/` is gitignored. Tests that need a fixture skip
  when it's absent.
- Q11: How are network-dependent tests kept out of the everyday offline run? **The `slow` marker**
  (AC4). `pytest -m "not slow"` is the offline suite.

## Changelog

- 2026-09-16: "Let's start with M0. Create a spec for it." Created a draft spec covering
  `requirements.txt`, the `extract_memes` package, the `main.py --help` entrypoint,
  `.gitignore`, and filling in CLAUDE.md's Code Conventions and Directory Structure. Five open
  questions were left to resolve before `ready`.
- 2026-09-16: "accept all proposed defaults and edit the ADR in place." Resolved all five open
  questions with the proposed defaults (no placeholder modules, `downloads/` + `output/`,
  ignore `.idea/`, Python 3.14 only, no linter yet) and moved status to `ready`. Edited ADR 002
  in place to match: M0 no longer lists placeholder modules, each later milestone names its own
  module, and the "M0–M4 built without specs" exception was replaced with a spec per milestone.
- 2026-09-16: Asked where tests go, then chose a `src/` layout, `pyproject.toml` as the only
  dependency file, an `extract-memes` console command instead of a root `main.py`, and pytest
  set up in M0. Rewrote the acceptance criteria around those choices (editable install, both
  `--help` commands, a passing `tests/` suite, updated `.gitignore` entries), and noted pytest and
  setuptools as new dependencies. Moved status back to `draft` since the criteria changed. Updated
  ADR 002 to match: M0 description, `src/` module paths for M1–M4, `extract-memes <url>` in M4,
  and tests added alongside each module.
- 2026-09-16: "implement the project setup." Implemented M0 per this spec's acceptance
  criteria: added `pyproject.toml` (Python 3.14, setuptools backend, `pytest` in a `dev` extra,
  `extract-memes` console script), `src/extract_memes/__init__.py` and `__main__.py`
  (argparse-based CLI), `tests/test_package.py` and `tests/test_cli.py`, and a `.gitignore`
  covering `.venv/`, `.idea/`, caches, `downloads/`, and `output/`. Verified with
  `pip install -e ".[dev]"`, both `--help` invocations, `pytest` (3 passed), and `git status`
  after placing dummy files in `downloads/`/`output/`. Filled in CLAUDE.md's "Code Conventions"
  and "Directory Structure" sections. Checked off all seven acceptance criteria and moved
  status to `implemented`.
- 2026-09-16 (commits `f8c227a`, `f4bfdf8`): Later milestones changed the skeleton without
  updating this spec. `.gitignore` swapped `output/` for `.runtime/` and added `/sample/`.
  Dependencies grew to `yt-dlp`, `opencv-python-headless`, `tqdm`, and `static-ffmpeg`. A `slow`
  pytest marker was registered.
- 2026-09-16: Documentation consolidation for the planned rebuild
  ([ADR 007](../../decisions/007-documentation-consolidation-for-rebuild.md)). Updated the ACs to the
  real skeleton: the `.runtime/` and `/sample/` ignores, the `slow` marker and three test tiers,
  and the no-import-side-effects rule. Added the full dependency table with known-good versions,
  the external prerequisites (`claude`, Node.js), the fixture inventory, and the permanent test
  video. Also declared `numpy` explicitly. Reset status to `ready` with unchecked ACs because the
  implementation will be erased and rebuilt.
- 2026-09-16: "Implement the project according to the docs in it. Commit each feature
  individually." Rebuild step 1 of [ADR 007](../../decisions/007-documentation-consolidation-for-rebuild.md).
  The M0 skeleton (`pyproject.toml`, `src/extract_memes/`, argparse `__main__.py`, `tests/`,
  `.gitignore`, CLAUDE.md sections) was already in place. Registered the `slow` marker under
  `[tool.pytest.ini_options]` (AC4). Added a test that imports every package module in a fresh
  interpreter, with a temporary cwd, and asserts `PATH` is unchanged and no files are written
  (AC2). Verified the editable install, both `--help` invocations, `pytest -m "not slow"`, and
  that dummy files in `downloads/`, `.runtime/x/`, and `sample/` stay out of `git status`. Checked
  AC2, AC3, AC5, AC6, and AC7. AC1 (runtime dependencies) and AC4 (one test module per source
  module) depend on the feature specs that come next, so status is `in-progress`.
- 2026-09-16: Completed the rebuild's project setup once the four feature modules existed.
  `pyproject.toml` now declares exactly `yt-dlp`, `static-ffmpeg`, `opencv-python-headless`,
  `numpy`, and `tqdm`, and `tests/` has all six test modules plus a shared `conftest.py` (the
  `short_video` fixture, which skips with a reason when `sample/short.mp4` is absent).
  Verified `pip install -e ".[dev]"` in a fresh CPython 3.14.7 virtualenv: it installed the
  known-good versions from Technical Notes, and `pytest -m "not slow"` passed there (60 passed)
  with no `claude` or `node` on `PATH`. Checked AC1 and AC4; status `implemented`.
