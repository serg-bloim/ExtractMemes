---
title: "Labeler Scene Sorting Tab"
status: implemented
created: 2026-10-08
updated: 2026-10-08
author: ""
depends-on: ["frame-labeler", "classifier-criteria"]
---

# Labeler Scene Sorting Tab

## Problem Statement

The labeler's strip lists scenes (rows) in video order. To analyze scenes (which ones score highest on a
criterion, which are flagged but not marked as memes, which were marked by hand) the developer has to
scroll the whole video and read every row. There is no way to bring the interesting scenes to the top.

## User Story

**Primary:**
As the developer analyzing scenes, I want a tab in the labeler's left panel where I build a list of sorters
(by a criterion's score, by label, ...) and reorder, invert, disable or remove them, so that the strip lists
the scenes that matter first.

## Acceptance Criteria

- [x] AC1: The second tab of the left panel (the empty "Test" tab, now removed) becomes the **Sort** tab. The strip,
      with its count, stays below the tabs on every tab ([frame-labeler](frame-labeler.md)).
- [x] AC2: The tab shows the list of sorters (empty at first) and an **Add sorter** button.
- [x] AC3: Add sorter opens a **wizard modal**: choose the sorter's type, then its parameters, then
      **Apply**, which appends the sorter to the end of the list; **Cancel** (or Esc) adds nothing.
- [x] AC4: Sorter types in the first version:
      - **Score**: a classifier criterion and how the scene's frames are reduced to one number
        (minimum, maximum, mean or median of the scene's frames that match the filters, or the score of
        the scene's middle frame, as the strip row shows), ascending or descending;
      - **Label**: the wizard picks one state (flagged, meme, not meme or unlabeled); scenes in that
        state go first and the others keep their order. A scene is in a state when any of its frames
        that match the filters is: flagged by the classifier, marked as a meme, marked as not a meme;
        unlabeled means none of the three. Several states are combined by stacking sorters
        (e.g. flagged first, then meme first).
- [x] AC5: Each sorter row shows a short description of what it sorts by, and, aligned to the right,
      four controls: **modify** (reopens the wizard with the sorter's values; Apply replaces it in
      place), **invert** (a checkbox: reverses this sorter's order), **disable** (a checkbox: the sorter
      is skipped but stays in the list) and **remove**.
- [x] AC6: Sorters can be **reordered by dragging** them in the list. The first sorter is the primary
      key, the next one breaks its ties, and so on; the last tiebreak is video order.
- [x] AC7: The strip applies the enabled sorters in list order whenever the list, a sorter's setting or
      the filters change. With no enabled sorter the strip is in video order, as now.
- [x] AC8: Sorting only changes the order of the strip's rows. Filters, selection, the frame views,
      the histogram and the keyboard navigation over rows (↑ ↓ / K J) follow the strip's current order.
- [x] AC9: The list of sorters is remembered in the browser across reloads (like the chosen tab).

## Out of Scope

- Saving sorter lists as named profiles on disk (the filter profiles stay as they are).
- Sorting the gallery, tiles or histogram.
- Sorting by anything not computed per frame already (e.g. Claude's verdicts from the scene database).
- Nested or conditional sorters.

## Technical Notes

- Client-side only (`tools/labeling/page.html`): every score, verdict and label is already in the page, so
  no server change is expected.
- The strip's virtualised rendering and `view` order (`rowShow`, `view`) are the integration points.

## Open Questions

- Q1 (resolved 2026-10-08): a scene is a strip row, a run of similar frames.
- Q2 (resolved 2026-10-08): sorting reorders the strip itself.
- Q3 (resolved 2026-10-08): the wizard chooses how a scene's score is obtained: min, max, mean, median
  or middle frame.
- Q4 (resolved 2026-10-08): option A, the label sorter puts one chosen state first; other orders come from
  stacking sorters.
- Q5 (resolved 2026-10-08): ↑ ↓ navigation and "select all" follow the sorted order.
- Q6 (default accepted 2026-10-08): the list is kept globally in the browser, not per video.

## Changelog

- 2026-10-08: The user asked for the second left-panel tab to hold scene sorters: sort by score, by
  label (flagged first, memes first), an Add sorter button opening a wizard modal (type, parameters,
  Apply), a list with right-aligned modify / invert / disable / remove, and drag-to-reorder. Drafted
  this spec and its open questions for review; no code yet.
- 2026-10-08: The user answered Q1, Q2, Q3 (adds "middle frame" to the reductions) and Q5; Q4 needed
  an explanation, Q6 is still on its proposed default.
- 2026-10-08: The user chose option A for Q4; Q6 stays on its default. Status set to `in-progress` and
  the Sort tab implemented in `tools/labeling/page.html`.
  Checked in Chrome on FtU4MuksCzE: score (max, desc) and label (meme first) orders, invert, disable,
  drag reorder, modify, remove, Esc, ↑ ↓ following the sorted order, and persistence across reloads.
- 2026-10-08: The user asked for icons instead of checkboxes and text glyphs: modify, invert, disable and
  remove are icon buttons; invert turns blue and disable red while on (aria-pressed).
