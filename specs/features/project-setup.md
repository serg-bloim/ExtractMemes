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

ExtractMemes has no code foundation: no declared dependencies, no source package, no entrypoint,
no tests, and no ignore rules. Without this, every later milestone (download, frame extraction,
classification, saving output) would have to decide where code and tests live and how the tool
runs, which leads to inconsistent structure. Large generated files like downloaded videos and
extracted images could also get committed by accident. This milestone sets up a minimal,
installable, tested skeleton that later milestones can build on.

## User Story

**Primary:**
As the developer of ExtractMemes, I want a minimal project skeleton that installs, runs, and has
a working test setup, so that each later milestone can add its module and its tests in an agreed
place without deciding the project structure again.

## Acceptance Criteria

- [x] AC1: A `pyproject.toml` at the project root declares the project, requires Python 3.14,
      has no runtime dependencies yet, and has a `dev` optional dependency group containing
      pytest. `pip install -e ".[dev]"` succeeds in a fresh Python 3.14 virtualenv. There is no
      `requirements.txt`.
- [x] AC2: The package lives at `src/extract_memes/` and has no pipeline modules yet. After the
      editable install, `python -c "import extract_memes"` succeeds from any directory.
- [x] AC3: After the editable install, both `extract-memes --help` and
      `python -m extract_memes --help` exit with code 0 and print usage text that describes the
      tool's purpose. There is no `main.py` at the project root.
- [x] AC4: A `tests/` folder exists at the project root. Running `pytest` from the project root
      passes, and the tests cover AC2 (the package imports) and AC3 (both `--help` commands).
- [x] AC5: A `.gitignore` exists. After installing, running the tool, running the tests, and
      placing a dummy file in `downloads/` and `output/`, `git status` shows none of the
      following as untracked: `.venv/`, `.idea/`, Python bytecode caches, `.pytest_cache/`,
      `*.egg-info/`, `downloads/`, or `output/`.
- [x] AC6: The "Code Conventions" section of `CLAUDE.md` is filled in with: the language and
      version (Python 3.14), where dependencies are declared (`pyproject.toml`) and how to install
      them, how to run the tool, how to run the tests, and the convention that each module gets
      matching tests under `tests/`.
- [x] AC7: The "Directory Structure" tree in `CLAUDE.md` shows `pyproject.toml`,
      `src/extract_memes/`, `tests/`, `downloads/`, and `output/`.

## Out of Scope

- Any pipeline behavior: downloading, frame extraction, classification, or saving output
  (milestones M1–M4 in ADR 002).
- Placeholder modules for later stages (`downloader.py`, `frame_extractor.py`, `classifier.py`,
  `pipeline.py`). Each milestone adds its own module and its tests.
- Adding pipeline dependencies such as `yt-dlp` or `opencv-python`. Each one is added and
  documented by the milestone spec that first uses it.
- Deciding how to handle tests that need network access or a real YouTube video (belongs to M1).
- Linter/formatter setup, CI, a lock file with pinned versions, or publishing to PyPI.

## Technical Notes

- Layout follows ADR 002 (`decisions/002-meme-extraction-pipeline-rollout-plan.md`).
- A virtualenv already exists at `.venv/`, created by PyCharm, on CPython 3.14.7.
- New dependencies introduced by M0:
  - `pytest` (dev only, in the `dev` optional group).
  - `setuptools` as the build backend in `pyproject.toml`. It finds packages under `src/`
    automatically. It's needed only to install the package, not at runtime.
- The `extract-memes` command is declared in `pyproject.toml`; `python -m extract_memes` works
  through `src/extract_memes/__main__.py`. The CLI can use the standard library (`argparse`).
- With the package installed in editable mode, pytest imports it without any extra path
  configuration.

## Open Questions

All resolved on 2026-09-16:

- Q1: Placeholder modules for later stages? **No.** Each milestone adds its own module when
  it's built, so there are no empty files.
- Q2: Default locations for downloaded videos and output? **`downloads/` and `output/`** at
  the project root, both gitignored.
- Q3: Gitignore `.idea/` or commit it? **Gitignore it entirely.**
- Q4: Supported Python versions? **3.14 only for now**, matching `.venv`.
- Q5: Linter/formatter in M0? **Deferred.** Revisit once there's meaningful code.
- Q6: Package layout? **`src/` layout** (`src/extract_memes/`).
- Q7: Where are dependencies declared? **`pyproject.toml` only**, with dev tools in a `dev`
  optional group. No `requirements.txt`.
- Q8: How is the tool run? **As a console command** (`extract-memes`), plus
  `python -m extract_memes`. No root `main.py`.
- Q9: Set up tests in M0 or later? **In M0.** A top-level `tests/` folder with pytest; M0's
  acceptance criteria are the first tests.

## Changelog

- 2026-09-16: "Let's start with M0. Create a spec for it." Created draft spec covering
  `requirements.txt`, the `extract_memes` package, the `main.py --help` entrypoint,
  `.gitignore`, and filling in CLAUDE.md's Code Conventions and Directory Structure. Five open
  questions left to resolve before `ready`.
- 2026-09-16: "accept all proposed defaults and edit the ADR in place." Resolved all five open
  questions with the proposed defaults (no placeholder modules, `downloads/` + `output/`,
  ignore `.idea/`, Python 3.14 only, no linter yet) and moved status to `ready`. Edited ADR 002
  in place to match: M0 no longer lists placeholder modules, each later milestone names its own
  module, and the "M0–M4 built without specs" exception was replaced with a spec per milestone.
- 2026-09-16: Asked where tests go, then chose a `src/` layout, `pyproject.toml` as the only
  dependency file, an `extract-memes` console command instead of a root `main.py`, and pytest
  set up in M0. Rewrote acceptance criteria around those choices (editable install, both
  `--help` commands, a passing `tests/` suite, updated `.gitignore` entries); noted pytest and
  setuptools as new dependencies. Moved status back to `draft` since criteria changed. Updated
  ADR 002 to match: M0 description, `src/` module paths for M1–M4, `extract-memes <url>` in M4,
  tests added alongside each module.
- 2026-09-16: "implement the project setup." Implemented M0 per this spec's acceptance
  criteria: added `pyproject.toml` (Python 3.14, setuptools backend, `pytest` in a `dev` extra,
  `extract-memes` console script), `src/extract_memes/__init__.py` and `__main__.py`
  (argparse-based CLI), `tests/test_package.py` and `tests/test_cli.py`, and a `.gitignore`
  covering `.venv/`, `.idea/`, caches, `downloads/`, and `output/`. Verified with
  `pip install -e ".[dev]"`, both `--help` invocations, `pytest` (3 passed), and `git status`
  after placing dummy files in `downloads/`/`output/`. Filled in CLAUDE.md's "Code Conventions"
  and "Directory Structure" sections. Checked off all seven acceptance criteria and moved
  status to `implemented`.
