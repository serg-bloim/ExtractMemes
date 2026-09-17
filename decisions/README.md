# Architecture Decision Records

This directory contains Architecture Decision Records (ADRs) for ExtractMemes.

---

## What is an ADR?

An ADR is a short document that captures a significant decision made about the architecture,
workflow, or technology of this project — along with the context that led to it and the
consequences of making it.

ADRs are **immutable records of intent**. They are not updated when a decision changes; instead,
a new ADR is written that supersedes the old one. This preserves the reasoning history.

---

## When to Write an ADR

Write an ADR when a decision:

- Is **hard to reverse** (e.g., choosing a framework, a database, a deployment platform)
- Affects **how the whole team or AI assistant works** (e.g., changing the spec workflow)
- Was **non-obvious** — where a reasonable person could have chosen differently
- Involves a **meaningful trade-off** between two or more options

You do NOT need an ADR for:
- Routine implementation choices (which component handles a piece of UI)
- Decisions easy to reverse with low cost
- Choices fully dictated by a spec's acceptance criteria

When in doubt, write the ADR. The cost of writing one is low; the cost of losing the context is high.

---

## ADR Format

```markdown
# NNN — Title

**Date:** YYYY-MM-DD
**Status:** Proposed | Accepted | Deprecated | Superseded by [NNN]

## Context

Why did this decision need to be made?

## Decision

What was decided? State it clearly and directly.

## Options Considered

List the alternatives evaluated before arriving at the decision.

## Consequences

Known trade-offs, costs, or follow-on effects.

## References

Links to related specs, external resources, or prior discussions.
```

---

## Index

| # | Title | Status | Date |
|---|-------|--------|------|
| 001 | [Spec-Driven Development Workflow](001-spec-driven-workflow.md) | Accepted | 2026-09-16 |
| 002 | [Meme Extraction Pipeline: Walking-Skeleton Rollout Plan](002-meme-extraction-pipeline-rollout-plan.md) | Partially superseded by 004, 005, 006 | 2026-09-16 |
| 003 | [Split JOURNAL.md Into a Flat Index With Detail Moved to Spec Changelogs](003-journal-changelog-split.md) | Accepted | 2026-09-16 |
| 004 | [Classify with Claude Code Now; Scan Low-Res, Extract High-Res](004-claude-classifier-and-dual-resolution-download.md) | Accepted; partially superseded by 006 | 2026-09-16 |
| 005 | [Checkpoint: Runtime Layout, 2fps Default, Meme-Reveal Prompt](005-runtime-layout-and-classifier-checkpoint.md) | Accepted | 2026-09-16 |
| 006 | [YouTube Downloads: Video-Only Formats, Node.js JS Runtime, Bundled ffmpeg](006-youtube-video-only-formats-and-download-toolchain.md) | Accepted (recorded retroactively) | 2026-09-16 |
| 007 | [Consolidate Specs and ADRs as the Source of Truth for a From-Scratch Rebuild](007-documentation-consolidation-for-rebuild.md) | Accepted | 2026-09-16 |
| 008 | [Iteration 2: Classify with a Hand-Built Image Heuristic; Keep the Claude Classifier as the Baseline](008-heuristic-classifier-iteration.md) | Accepted | 2026-09-16 |
| 009 | [Iteration 3: Scan Frames in Memory; Separate, Opt-In Low-Res Output](009-in-memory-scan-and-resolution-folders.md) | Proposed | 2026-09-17 |