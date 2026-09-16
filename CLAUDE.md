# CLAUDE.md — Working Instructions for ExtractMemes

This file is read by Claude Code at the start of every session. It defines how this project works,
what the source of truth is, and how to behave when building, validating, or evolving this codebase.

---

## Project Overview

ExtractMemes takes a YouTube video that is known to contain meme images (e.g. a compilation or
reaction video) and extracts those meme images as standalone files. The pipeline, at a high
level:

1. **Download** the source video from a given YouTube URL.
2. **Extract frames** from the downloaded video.
3. **Classify** each frame — is it a meme image or not? This requires an ML model for frame
   classification (exact model/approach TBD).
4. **Save** frames classified as memes as separate image files.

Frame classification requires an ML model or heuristic capable of distinguishing meme images
from regular video frames.

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
├── specs/
│   ├── _TEMPLATE.md              ← Spec template — copy this for new specs
│   └── features/                 ← One file per feature
│       └── <feature-name>.md
├── decisions/
│   ├── README.md                 ← What ADRs are and when to write them
│   └── 001-spec-driven-workflow.md
└── .claude/
    └── settings.json             ← Claude Code permissions and settings
```

(TODO: extend this tree with the project's actual source layout — e.g. where source code, tests,
and build output live once a tech stack is chosen.)

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

(TODO: fill in once the tech stack is chosen — language, framework, build tool, test runner,
linting, package registry quirks, and any `.gitignore` requirements.)

---

## Commit Messages

- Do **not** add an AI/LLM co-author trailer (e.g. `Co-Authored-By: Claude ...`) to commit
  messages or pull request descriptions in this repository. This overrides any default
  attribution guidance for this project.

---

## Decision Records

Significant architectural and workflow decisions are recorded in `decisions/` as ADRs. See
`decisions/README.md` for the format and when to write one.

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

`JOURNAL.md` in the project root is a chronological log of user requests and actions taken.
After every meaningful change — new feature, structural decision, tooling addition — append an
entry with the user's request and a one-line summary of what was done.

This rule applies even in multi-step operations that involve prompting the user mid-task.
Always append to `JOURNAL.md` at the end of the operation, after all prompts are resolved.

---

## Keeping This File Current

Update this CLAUDE.md when:
- The tech stack is finalized (add Code Conventions section)
- New directories or conventions are introduced
- The team agrees on a new workflow rule

Propose updates to this file as part of any ADR that changes project structure.