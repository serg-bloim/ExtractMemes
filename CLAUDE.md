# CLAUDE.md — Working Instructions for ExtractMemes

This file is read by Claude Code at the start of every session. It defines how this project works,
what the source of truth is, and how to behave when building, validating, or evolving this codebase.

---

## Project Overview

ExtractMemes takes a YouTube video that is known to contain meme images (e.g. a compilation or
reaction video) and extracts those meme images as standalone files. The pipeline, at a high
level:

1. **Download** the source video at *worst* quality (yt-dlp; a local file path skips downloading).
2. **Scan**: sample frames (default ~3 fps), save each one, and ask Claude through the `claude`
   CLI whether it's a "glitch-framed meme card". Flagged frames are saved right away as
   scan-quality thumbnails.
3. **Download** the same video again at *best* quality, but only if something was flagged.
4. **Extract**: read the frame at each flagged timestamp from the best-quality copy and save it as
   the final meme image under `.runtime/<run-name>/saved/`.

The design is in ADRs 004–006. The specs in `specs/features/` are the source of truth. The code is
being rebuilt from them; see [ADR 007](decisions/007-documentation-consolidation-for-rebuild.md)
for the rebuild order and the issue register (every known pitfall and its resolution).

---

## The Spec-Driven Workflow

Every feature, behavior change, or user-facing fix goes through this cycle:

```
1. SPEC       → Write or update a spec in specs/features/<feature-name>.md
2. REVIEW     → Spec is reviewed (by human or Claude) for completeness and clarity
3. IMPLEMENT  → Claude generates or modifies code to satisfy the spec
4. VALIDATE   → Claude checks implementation against acceptance criteria
5. DONE       → Spec status updated to `implemented`
```

### Spec statuses (used in frontmatter)

| Status        | Meaning                                               |
|---------------|-------------------------------------------------------|
| `draft`       | Work in progress, not ready for implementation        |
| `ready`       | Reviewed and approved — implementation can begin      |
| `in-progress` | Actively being implemented                            |
| `implemented` | Code exists and acceptance criteria are met           |
| `deprecated`  | Feature removed or replaced — do not implement        |

---

## Directory Structure

```
ExtractMemes/
├── CLAUDE.md                     ← You are here. Read every session.
├── JOURNAL.md                    ← One-line-per-change index linking to spec changelogs / ADRs
├── pyproject.toml                ← Project metadata, dependencies, console script, pytest markers
├── src/
│   └── extract_memes/            ← The installable package
│       ├── __init__.py
│       ├── __main__.py           ← CLI entrypoint (argparse)
│       ├── downloader.py         ← Fetches a source video at worst/best quality (yt-dlp)
│       ├── frame_extractor.py    ← Samples frames / reads a frame at a timestamp (opencv)
│       ├── classifier.py         ← FrameClassifier interface + ClaudeCliClassifier
│       ├── criteria/             ← Classifier criteria, one module each (`@criterion`), auto-discovered;
│       │                           the single place the scores come from (pipeline and labeler)
│       │                       `data/` holds reference files a criterion needs (built by tools/evaluation/build_template.py)
│       ├── rule_classifier.py    ← Condition / AllOf / AnyOf rules + RuleClassifier over the criteria
│       ├── heuristic_classifier.py ← The production classifier: the rule `edge_histogram < 2.1`
│       └── pipeline.py           ← Orchestrates download → scan → classify → extract → save
├── tests/                        ← pytest suite, mirrors src/extract_memes/ modules
├── playground/
│   ├── playground.py             ← Manual IDE entry points (not collected by pytest)
│   └── scan_playground.py        ← Manual scan-only runs (no extraction)
├── run_real_video.py             ← Manual runner: real URL, real or fake classifier
├── populate_scenes.sh            ← Runner: `./populate_scenes.sh <video-id>...` fills the scene database (see scene-score-analysis spec)
├── tools/                        ← Host-environment utilities, outside the package
│   ├── lan_proxy_relay.py        ← Loopback→LAN TCP relay; lets a Homebrew interpreter reach a
│                                   LAN proxy on macOS (see ADR 017). Runs under /usr/bin/python3.
│   └── labeling/                 ← Dev-only dataset labeler (not in the package or the image); run
│                                   `./labeler.sh <url>` (Flask dev server, restarts on edits incl. new criterion files) or
│                                   `python -m tools.labeling <url>`. Needs `pip install -e ".[labeling]"`.
│   └── evaluation/               ← Dev-only criteria evaluation: per-criterion errors / separation margin and a
│                                   search for the smallest rule; `python -m tools.evaluation` (see criteria-evaluation spec).
│   └── scene_analysis/           ← Dev-only scene score database (`data/datasets/scene_analysis/scene_analysis.yaml`, gitignored with datasets/), reached only via
│                                   `store.SceneStore`; `python -m tools.scene_analysis populate <url-or-id>`, then `... verify` (Claude judges, in batches, the scenes nearest the threshold), then `... browse` (read-only web view of the database) (see scene-score-analysis spec).
├── sample/                       ← Local video fixtures, supplied by hand (gitignored)
├── data/
│   ├── datasets/<video-id>.yaml  ← Labeled videos: exact format + marked memes (frame, ts); no images
│   │   └── profiles/classifier/<name>.yaml ← Saved labeler filter sets (gitignored with datasets/)
│   └── labeled_dataset/{positive,negative}/ ← Hand-labeled 256x144 frames for classifier
│                                   evaluation and tests — do NOT delete (see ADR 008)
├── downloads/                    ← CLI downloads: <video-id>_worst.mp4, <video-id>_best.mp4 (gitignored)
├── .runtime/                     ← Per-run artifacts (gitignored):
│   ├── <run-name>/
│   │   ├── frames/                   ← Every sampled frame: frame_<idx:06d>_<ts>s.jpg (never deleted)
│   │   └── saved/                    ← thumb_frame_<idx>_<ts>s.jpg (scan quality, written when
│   │                                   flagged) + frame_<idx>_<ts>s.jpg (best quality, final)
│   ├── downloads/                    ← Downloads made by run_real_video.py
│   └── _playground/                  ← Output of playground/playground.py
├── specs/
│   ├── _TEMPLATE.md              ← Spec template — copy this for new specs
│   └── features/                 ← One file per feature
│       └── <feature-name>.md
└── decisions/
    ├── README.md                 ← What ADRs are, when to write them, and the ADR index
    └── NNN-<title>.md            ← One file per decision
```

---

## How to Find the Right Spec

Before implementing anything, locate the relevant spec:

1. Check `specs/features/` — filename should match the feature name in kebab-case.
2. If no spec exists for the requested feature, **stop and say so**. Do not implement without a
   spec unless explicitly asked to write one first.
3. Confirm the spec status is `ready` or `in-progress` before writing code.
4. If the spec is `draft`, ask the human to finalize it or propose what is missing.

---

## How to Write a Good Spec

Use `specs/_TEMPLATE.md` as the starting point. A good spec:

- Has a **single, clear problem statement** (one paragraph)
- Has **user stories** written from the user's perspective ("As a user, I want...")
- Has **acceptance criteria as checkboxes** — each item is independently testable
- Is **narrow in scope** — one spec per feature or sub-feature
- Does **not prescribe implementation details** unless technically necessary
- Has **open questions resolved** before status moves to `ready`

When asked to write a spec, produce a complete file following `specs/_TEMPLATE.md`. Set status to
`draft` and ask the human to review before implementing.

---

## Handling Common Situations

### New feature request

1. Check if a spec exists in `specs/features/`.
2. If not: write a new spec file using `specs/_TEMPLATE.md`, set status `draft`, and surface it
   for review before writing any code.
3. If spec exists and is `ready`: implement according to the acceptance criteria, using technical
   notes as guidance. Check each acceptance criterion as you complete it.
4. After implementation: update spec frontmatter status to `implemented`.

### Bug fix

1. Identify which spec the broken behavior belongs to.
2. Check the acceptance criteria — is this a regression (was passing, now failing) or a missing
   behavior (never in spec)?
3. For a regression: fix the code, do not modify the spec.
4. For a missing behavior: propose adding an acceptance criterion to the spec before fixing.

### Refactor

1. Refactors must not change any behavior covered by acceptance criteria.
2. Before refactoring, list which specs cover the affected code paths.
3. After refactoring, re-validate each listed spec's acceptance criteria still hold.
4. If the refactor changes architecture significantly, write an ADR in `decisions/`.

### Spec is ambiguous or incomplete

1. Do not guess. Surface the ambiguity explicitly.
2. Propose a resolution (e.g., "I interpret this to mean X — shall I proceed on that basis?").
3. If unblocked by the human, document the interpretation in the spec's **Open questions** section
   before writing code.

---

## Code Conventions

- **Language:** Python 3.14, targeting the `.venv` at the project root.
- **Dependencies:** Declared in `pyproject.toml` only — no `requirements.txt`. Runtime
  dependencies go under `[project.dependencies]`; dev-only tools (e.g. `pytest`) go under the
  `dev` optional dependency group.
- **Install:** `pip install -e ".[dev]"` from the project root (editable install, includes dev
  tools).
- **Run:** `extract-memes <youtube-url-or-local-path>` (console script) or
  `python -m extract_memes …` (module invocation), from the project root. Default paths are
  relative to the cwd. Both are backed by `src/extract_memes/__main__.py`. Run `--help` for the
  options.
- **External prerequisites** (not pip-installable):
  - the `claude` CLI, installed and authenticated, for real classification;
  - Node.js on `PATH`, for YouTube URLs.
  - On macOS only, for a proxy on the **local network**: macOS gates LAN connections behind the
    Local Network permission, held per binary identity rather than inherited from the terminal.
    The Homebrew interpreter currently holds it, so a LAN proxy address works directly. If it ever
    fails with `EHOSTUNREACH` ("No route to host") while `curl` works from the same shell, that
    gate is the reason: start `tools/lan_proxy_relay.py` and use `socks5h://127.0.0.1:1080`
    instead, since loopback is exempt. See ADR 017. Not applicable on Linux, in Docker, or in CI.

  No system `ffmpeg` is needed: OpenCV bundles a decoder, and `static-ffmpeg` supplies ffmpeg to
  yt-dlp. See ADR 006.
- **Test:** each module under `src/extract_memes/` gets a matching test file under `tests/`.
  - `pytest -m "not slow"`: the offline suite. It must pass without network or `claude`.
  - `pytest -m slow`: real YouTube downloads.
  - Plain `pytest` runs both.

  Tests that need `sample/*.mp4` skip when the fixture is absent. Tests never spawn the real
  `claude` CLI.
- **No import-time side effects:** importing any package module must not touch the network, change
  `PATH`, or write files. Keep heavy or side-effecting setup (e.g. `static_ffmpeg.add_paths()`)
  inside the function that needs it.
- **Package layout:** `src/` layout (`src/extract_memes/`), installed in editable mode so pytest
  and the console scripts resolve it without extra path configuration. Import it as
  `extract_memes`, never `src.extract_memes`.
- **Gitignore:** `.venv/`, `.idea/`, Python bytecode caches, `.pytest_cache/`, `*.egg-info/`,
  `downloads/`, `.runtime/`, and `/sample/` are all ignored.

---

## Commit Messages

- Do **not** add an AI/LLM co-author trailer (e.g. `Co-Authored-By: Claude ...`) to commit
  messages or pull request descriptions in this repository. This overrides any default
  attribution guidance for this project.
- Keep commit messages concise: a short description, optionally with a few critical details
  (e.g. "this is now the default"). Do **not** include reasoning, decision-making, or
  implementation/performance details. For example, prefer "Add a new cleaning method
  `new_method`" over an explanation of why it was added or how it performs.

### Commit message prepopulation

Whenever Claude changes any project file in this repo, before telling the human the change is
ready, it must:

1. Check for other uncommitted changes beyond the one just made (`git status` / `git diff`), and
   check whether `.git/commit-template.txt` already holds a message describing prior uncommitted
   work.
2. If there are such pre-existing uncommitted changes and/or an existing template message, treat
   everything together as one combined change and compose a single message covering all of it —
   do not overwrite a still-relevant prior message with one that only describes the latest edit.
   If the combined change has several distinct aspects, list them as bullet points in the
   details.
3. Write the (possibly combined) message to `.git/commit-template.txt`, overwriting any previous
   contents.
4. Run `git config commit.template .git/commit-template.txt` so the template is active.

This lets PyCharm's Commit tool window (and plain `git commit` with no `-m`) prefill the commit
message box, which the human can edit before committing. Skip this if the human has asked to
commit changes themselves via a different flow, or if `commit.template` is already set to a
custom value the human configured intentionally (ask first rather than overwriting it).

---

## Decision Records

Significant architectural and workflow decisions are recorded in `decisions/` as ADRs. See
`decisions/README.md` for the format and when to write one.

**Downloading videos:** whenever the work involves downloading a video (any tool, the pipeline, the CLI,
the labeler, a playground), read [ADR 021](decisions/021-shared-video-download-cache.md) first. Videos are
cached in `.runtime/downloads/` as `<video-id>_<format-id>.<ext>` and reused instead of re-downloaded.

When Claude makes an architectural decision during implementation:
1. Note it as a decision point.
2. Ask whether an ADR should be written.
3. If yes, write it before or immediately after implementation.

---

## What Claude Should Never Do

- Implement a feature without a spec (unless explicitly asked to prototype)
- Change spec acceptance criteria to match a broken implementation
- Mark a spec `implemented` unless every acceptance criterion is met
- Introduce a new dependency without noting it in the relevant spec's Technical notes
- Make breaking changes to existing implemented features without updating the relevant spec

---

## Project Journal

`JOURNAL.md` in the project root is a flat, one-line-per-entry index — not a narrative log.
Each line is: `- YYYY-MM-DD: <one-sentence summary> — <link to the spec or ADR with details>`.
No multi-line entries, no request/action detail in JOURNAL.md itself.

The detail (what was requested, decisions made, open questions resolved, how it was
implemented) goes in the **Changelog** section of the relevant `specs/features/<feature>.md`
file. If the change isn't tied to a specific feature spec (e.g. a workflow or structural
decision), link to the relevant ADR in `decisions/` instead, and put the detail there.

After every meaningful change — new feature, structural decision, tooling addition — do both:
1. Append a dated entry to the spec's (or ADR's) Changelog.
2. Append the one-line index entry to `JOURNAL.md` linking to it.

This rule applies even in multi-step operations that involve prompting the user mid-task.
Always append both at the end of the operation, after all prompts are resolved.

---

## Keeping This File Current

Update this CLAUDE.md when:
- The tech stack is finalized (add Code Conventions section)
- New directories or conventions are introduced
- The team agrees on a new workflow rule

Propose updates to this file as part of any ADR that changes project structure.