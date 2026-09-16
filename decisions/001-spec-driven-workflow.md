# 001 — Spec-Driven Development Workflow

**Date:** 2026-09-16
**Status:** Accepted

---

## Context

ExtractMemes is being built with AI-assisted development (Claude Code) as a first-class part of
the workflow. This introduces a question that doesn't arise in traditional human-only teams:
**how does an AI assistant know what to build, and how does it know when it's done?**

Without a structured approach, AI-assisted development tends toward one of two failure modes:

1. **Context collapse**: The AI implements based on vague prompts, produces something plausible
   but not what was actually wanted, and iterations are spent correcting drift rather than making
   progress.
2. **Over-specification in chat**: The human over-explains in a long conversation message,
   producing code that matches the message but has no persistent, reviewable source of truth.
   The next session starts cold.

Both failure modes share a root cause: **requirements exist only in conversation, not in the
repository**. The AI has no stable ground truth to work from, validate against, or return to
in future sessions.

---

## Decision

We will use a **spec-driven development workflow** in which:

1. A markdown spec file is written (by a human or Claude) **before implementation begins** for
   every non-trivial feature.
2. Specs are stored in `specs/features/` and follow a standard template (`specs/_TEMPLATE.md`).
3. Specs are the **authoritative definition of done**: a feature is complete when all acceptance
   criteria checkboxes in its spec are satisfied — not when the code compiles or looks right in
   the browser.
4. `CLAUDE.md` contains the full working instructions for Claude Code, including how to find,
   read, and act on specs.
5. Claude is instructed to refuse to implement without a spec (except when explicitly asked to
   prototype) and to refuse to mark a spec done unless all criteria are checked.

---

## Options Considered

### Option A: Prompt-driven (no persistent specs)

Write detailed prompts per session. No separate spec files.

**Rejected:** Context is lost between sessions. Acceptance criteria exist only in the prompt,
making systematic validation or re-validation after refactors impossible.

### Option B: Ticket-driven (specs live in Jira/Linear/GitHub Issues)

Write acceptance criteria in an external issue tracker.

**Rejected for v1:** Requires integration with an external tool, separates the spec from the
code repository, and adds overhead without proportional benefit for a small team. Revisit if
the project scales.

### Option C: Spec-driven with markdown files in the repo (chosen)

Write specs in `specs/features/` as markdown files, co-located with the codebase.

**Chosen because:**
- Specs are version-controlled alongside the code they describe.
- Claude Code can read them directly with no external API calls.
- Pull requests can include spec updates alongside code changes, making review coherent.
- Status fields in frontmatter give a machine-readable lifecycle signal.

### Option D: README-per-feature

Store specs as README files inside feature directories.

**Rejected:** Requires a code structure to exist before a spec can be placed, inverting the
spec-first principle. Also makes it harder to list all specs in one place.

---

## Consequences

**Positive:**
- Every session, Claude has a complete, structured understanding of what is intended.
- Acceptance criteria serve as a built-in test plan Claude can reference during validation.
- The spec corpus becomes living documentation that reflects the real product.
- Humans reviewing the project can read specs to understand intent without reading code.

**Negative / costs:**
- Writing a spec before every feature adds friction for small changes or quick experiments.
  This is intentional — it forces clarity before effort. Prototypes and spikes are exempt;
  production features are not.
- Specs can drift from implementation if forgotten after changes. Mitigation: Claude is
  instructed to never mark a spec `implemented` unless all criteria are checked.
- New contributors must read `CLAUDE.md` to understand the workflow.

---

## References

- `CLAUDE.md` — full working instructions including spec-driven workflow details
- `specs/_TEMPLATE.md` — the spec template this workflow depends on
