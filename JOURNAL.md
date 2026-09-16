# Project Journal

Chronological log of requests and actions taken. Updated after every meaningful change.

---

## 2026-09-16

**Request:** Describe the meme-extraction pipeline (download YouTube video → extract frames →
classify frames with an ML model → save detected memes) and update CLAUDE.md with it.

**Action:** Added a Project Overview to CLAUDE.md describing the pipeline at a high level.

**Request:** "Plan the overall workflow" — asked for the high-level roadmap (milestones, dev
process setup) rather than classifier implementation details.

**Action:** Planned a walking-skeleton rollout: build download → extract → save end-to-end
first with classification stubbed behind an interface, deferring the real classifier choice to
its own milestone once real extracted frames exist to evaluate against. Saved the plan as
`decisions/002-meme-extraction-pipeline-rollout-plan.md` and indexed it in `decisions/README.md`.

**Follow-up:** User noted that the meme-extraction-pipeline spec was too broad (entire project
goal, not a smaller requirement). Deleted it. Updated ADR 002 and CLAUDE.md to remove references
to the spec file. Individual milestone specs will be written as each becomes `ready` to implement.

**Request:** "Let's start with M0. Create a spec for it."

**Action:** Created draft spec `specs/features/project-setup.md` covering requirements.txt, the
`extract_memes` package, the `main.py --help` entrypoint, `.gitignore`, and filling in CLAUDE.md's
Code Conventions and Directory Structure. Five open questions need answers before it moves to `ready`.

**Request:** "accept all proposed defaults and edit the ADR in place"

**Action:** Resolved all five open questions in the M0 spec with the proposed defaults (no
placeholder modules, `downloads/` + `output/`, ignore `.idea/`, Python 3.14 only, no linter yet)
and moved it to `ready`. Edited ADR 002 in place: M0 no longer lists placeholder modules, each
later milestone names its own module, and the "M0–M4 built without specs" exception was replaced
with a spec per milestone.

**Request:** Asked where tests go, then chose a `src/` layout, `pyproject.toml` as the only
dependency file, an `extract-memes` console command instead of a root `main.py`, and pytest set
up in M0.

**Action:** Rewrote the M0 spec's acceptance criteria around those choices (editable install,
both `--help` commands, a passing `tests/` suite, updated `.gitignore` entries) and noted pytest
and setuptools as new dependencies. Moved the spec back to `draft` because its criteria changed.
Updated ADR 002: M0 description, `src/` module paths for M1–M4, `extract-memes <url>` in M4, and
tests added alongside each module.

**Request:** "implement the project setup"

**Action:** Implemented M0 per `specs/features/project-setup.md`: added `pyproject.toml`
(Python 3.14, setuptools backend, `pytest` in a `dev` extra, `extract-memes` console script),
`src/extract_memes/__init__.py` and `__main__.py` (argparse-based CLI), `tests/test_package.py`
and `tests/test_cli.py`, and a `.gitignore` covering `.venv/`, `.idea/`, caches, `downloads/`,
and `output/`. Verified with `pip install -e ".[dev]"`, both `--help` invocations, `pytest`
(3 passed), and `git status` after placing dummy files in `downloads/`/`output/`. Filled in
CLAUDE.md's "Code Conventions" and "Directory Structure" sections. Checked off all seven
acceptance criteria and moved the spec to `implemented`.