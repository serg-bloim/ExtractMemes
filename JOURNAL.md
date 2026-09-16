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