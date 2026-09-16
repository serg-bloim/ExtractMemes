# 003 — Split JOURNAL.md Into a Flat Index With Detail Moved to Spec Changelogs

**Date:** 2026-09-16
**Status:** Accepted

---

## Context

`JOURNAL.md` had grown into a full narrative log: every request and every action taken was
written out in multi-paragraph entries. After one milestone (M0) this was already long and
duplicated detail that also belonged with the spec it was about — the M0 spec and JOURNAL.md
told overlapping stories, and JOURNAL.md would only get harder to scan as more milestones land.

The user asked to keep JOURNAL.md simple and move the detail somewhere else.

## Decision

`JOURNAL.md` becomes a flat, one-line-per-entry index: date, one-sentence summary, and a link
to where the detail lives. No multi-line entries.

The detail (what was requested, decisions made, open questions resolved, how it was
implemented) moves to a `## Changelog` section on the relevant `specs/features/<feature>.md`
file — added to `specs/_TEMPLATE.md` so every new spec has one. When a change isn't tied to a
specific feature spec (a workflow or structural decision, like this one), the JOURNAL.md entry
links to the relevant ADR in `decisions/` instead, and the ADR's own Context/Decision sections
carry the detail.

After every meaningful change, both the spec's (or ADR's) detail and the JOURNAL.md index entry
get appended — this still applies even across multi-step operations that prompt the user
mid-task, appended once at the end after all prompts are resolved.

## Options Considered

1. **Chosen:** One-line JOURNAL.md index; detail in the spec's Changelog (or ADR, if not
   spec-tied).
2. Detail moved into git commit messages instead, with JOURNAL.md linking to commit hashes.
   Rejected for this project: commit messages don't capture the back-and-forth of a
   conversation (mid-task prompts, resolved open questions) as naturally as a spec section that
   sits next to the acceptance criteria it explains.
3. Only log decision-worthy entries at all (routine implementation work left untracked outside
   git). Rejected: loses the "what was asked" record for routine milestone work, which the user
   wants kept, just not in JOURNAL.md itself.

## Consequences

**Positive:**
- JOURNAL.md stays scannable as a chronological index regardless of project size.
- Spec detail lives next to the acceptance criteria and open questions it explains, instead of
  in a separate file telling an overlapping story.

**Negative / costs:**
- Two places to update per change instead of one (the spec/ADR Changelog, then the JOURNAL.md
  index line) — accepted as a small overhead for a clearer split.
- Changes not tied to a spec or ADR (rare, but possible) have no natural home for their detail;
  if that comes up, the ADR criteria in `decisions/README.md` should be revisited.

## References

- `CLAUDE.md` — "Project Journal" section
- `specs/_TEMPLATE.md` — Changelog section
- `specs/features/project-setup.md` — first spec retrofitted with a Changelog
