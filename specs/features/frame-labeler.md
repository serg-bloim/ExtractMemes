---
title: "Frame Labeler"
status: in-progress
created: 2026-10-07
updated: 2026-10-07
author: ""
depends-on: ["labeled-video-dataset"]
---

# Frame Labeler

## Problem Statement

To build a dataset ([labeled-video-dataset](labeled-video-dataset.md)) someone has to look through a
video and mark where the memes are. There is no tool for that: scanning thousands of frames by
hand in a video player and writing timestamps down is slow and error-prone.

This is development tooling, outside the installable package, and is not part of the production
image or the GitHub Actions install.

## User Story

**Primary:**
As the developer improving the classifier, I want a simple web page that shows a video's frames in
a scrollable vertical strip with the classifier's verdict and per-criterion scores beside each,
lets me filter on those, select a frame, step through its neighbours and mark which ones are
memes, and saves the marks to the dataset file, so that I can label a video quickly, see where the
classifier disagrees with me, and keep the result in the repo.

## Acceptance Criteria

- [x] AC1: A command run from the project root (e.g. `python -m tools.labeling <youtube-url>`)
      starts a local web server on `127.0.0.1`, prints the page address, and needs no internet
      access beyond fetching the video itself.
- [x] AC2: Given a URL with no dataset yet, it downloads the video at the lowest quality (the
      "worst" tier; `--format-id` overrides) and creates `data/datasets/<video-id>.yaml` with the
      video identity on the first mark. Given a URL or id that already has a dataset, it loads that
      exact format (dataset AC5/AC6) and shows the existing marks.
- [x] AC3: The page has a **vertical strip of thumbnails** on one side. It scrolls through the whole
      video and shows **every frame the scan classifies**: the same frames `sample_frames` yields
      at the scan rate (`--fps`, default 3.0 like the pipeline), chosen by the same rule
      (every `max(1, round(native_fps / fps))`-th decoded frame). So at 3 fps the strip has 3 rows
      per second, and the rows are exactly the frames a classifier would see. Each thumbnail shows
      its timestamp and index, thumbnails load lazily as they scroll into view, and marked frames
      carry a visible indicator. Clicking a thumbnail selects that frame. A mark on a frame that
      isn't a strip row (set by stepping) is shown on the nearest row before it.
- [x] AC4: A large view shows the selected frame with its timestamp and index. Left/right step one
      frame, shift+left/right one second, and a jump-to-timestamp box moves the selection; holding a
      key repeats. The strip follows the selection, and neighbouring frames are preloaded so
      stepping feels immediate. Stepping is by native frame, not by the strip's granularity.
- [x] AC5: A key (and a button) toggles "meme" on the selected frame. Marks can be added, moved
      (select another frame of the same meme and re-mark it) and removed from the strip or the
      large view. A list of all marks lets me jump to one.
- [x] AC6: Keys jump to the next/previous mark, and to the next frame not within ±1 s of any mark,
      so unlabeled stretches can be skimmed.
- [x] AC7: Marks are written to the dataset file on every change (no separate save step), through
      the server, as `meme_ts`/`meme_frame` per meme (dataset AC3). The file stays valid (sorted, no
      duplicates). Closing the browser or the server loses nothing.
- [x] AC8: The index and timestamp shown for a frame are the frame's own (dataset AC4), the same
      values the dataset loader reproduces; selecting a frame and marking it then reloading gives
      the same frame back.
- [x] AC9: No frame images are written into the repo. Any thumbnail or index cache goes under
      `.runtime/` (gitignored).
- [x] AC10: The server binds only to loopback and rejects requests whose paths aren't the page, its
      own API, a thumbnail or a frame request.
- [x] AC11: This code is not in the installable package, and its dependency (PyYAML) is in an
      optional group, not `[project.dependencies]` (dataset AC10).
- [x] AC12: Each strip row and the large view show **classifier info** for the frame: the verdict of
      the production classifier (`HeuristicClassifier`: flagged or not) and the score of every
      registered criterion (at least `band` and `texture` from `HeuristicClassifier.scores`), next to
      the human label (marked or not). Scores are computed on the scanned frames only, in the same
      sequential pass that builds the thumbnails, and cached under `.runtime/` (AC9), so scrolling
      and filtering don't decode video.
- [x] AC13: The criteria shown are the ones in `extract_memes.criteria` (see
      [classifier-criteria](classifier-criteria.md)), all of them, discovered at start: the labeler
      has no list of its own and copies no scoring code, so its scores are the pipeline's. The
      verdict is the one of `HeuristicClassifier()`, and the thresholds drawn are the ones that
      classifier's rule compares each criterion with. A new criterion file shows up in the page
      after the automatic restart, and only its scores are computed; changing a criterion's code (or
      the classifier) recomputes only what depends on it.
- [x] AC14: The strip can be **filtered**, and the filter hides rows that don't match, with a count
      of how many remain:
      - by human label: marked / unmarked;
      - by classifier verdict: flagged / not flagged;
      - by each criterion's score: a min/max range;
      - and combinations of these, so "flagged but not marked" (false positives) and "marked but
        not flagged" (misses) are one click each.
      Each filter line has its own small reset button that puts only that filter back to its default
      (greyed out when it already is); "Reset" still clears them all.
      Prev/next-in-filter keys jump to the neighbouring matching row, and the filter survives
      marking and unmarking (a row that stops matching disappears after the change, not during it).
- [ ] AC15: **Multi-selection.** Shift+click on a strip row selects every row (of those currently
      shown, after filtering) from the last clicked row to this one; Cmd/Ctrl+click adds or removes
      one row. The selected rows are highlighted and counted, and the mark key then applies to all of
      them in one request: if every selected row is marked it unmarks them, otherwise it marks the
      unmarked ones. The A key selects every row the strip shows (so, with filters, all the frames that pass them). Esc clears the selection and leaves no frame selected (the large view is empty and the mark keys do nothing until a frame is selected again; the arrow keys resume from the last frame). A plain click or keyboard navigation replaces the selection.
- [ ] AC16: A second human label, **not a meme**, can be set on the selected frame or on a
      multi-selection with its own key (X) and button, and cleared the same way. A frame is a meme,
      a not-meme or unlabeled, never two: setting one replaces the other. Not-memes are saved to the
      dataset's `not_memes` list on every change, shown on strip rows and in the large view, listed
      beside the marks, and the human-label filter has meme / not meme / unlabeled.
- [ ] AC17: `./labeler.sh <youtube-url-or-id> [--fps N] [--format-id ID] [--port N] [--proxy URL]`
      from anywhere starts the server with auto-reload: editing, adding or removing a Python file
      under `tools/labeling/` or `src/extract_memes/` restarts it, and a browser refresh picks up `page.html`. Marks survive a restart.
- [ ] AC18: **Choosing the video in the page.** An "Open video" button opens a modal where I paste
      a YouTube URL or id. The server looks it up (metadata only, nothing downloaded) and the modal
      shows the video's thumbnail, title, uploader, duration and upload date, and a list of its
      video formats (resolution, fps, codec, container, size, format id; AV1 flagged as possibly not
      decodable here), with one preselected by these priorities: at least 25 fps, then the smallest resolution, then not AV1. Picking a format and confirming
      loads that video on the server in the background, showing what it is doing (downloading /
      indexing, with a percentage), and switches the page to it when ready; a failure is shown in
      the modal and the video that was open stays open. A video that already has a dataset is
      shown with its dataset (counts of memes and not-memes) and can only be loaded in the format
      the dataset records. The modal also has a dropdown of the videos that already have a dataset (with their meme and not-meme counts); picking one looks it up like a pasted id. The
      command and scripts may be started with no video at all (and reopen the last one when there
      is one), in which case the page opens on the modal. Only YouTube video ids are accepted: the
      server builds the URL itself from the id and never fetches an address supplied by the page,
      and the format id is checked to be a plain id, not a yt-dlp format expression.
- [ ] AC19: **Histogram view.** The main area has a switch between the frame view and a histogram
      view (button and the H key). The histogram view has a list of metrics to chart, starting with
      the classifier criteria's scores (`band`, `texture`, ... from the registry; later metrics
      join the same list), a bin count and a log-scale option. It charts the metric over:
      - **the frames the strip shows** (all of them when no filter is set) when no frame is
        selected, i.e. it follows the strip's filters;
      - **only the selected frames** when one or several are selected (a single frame shows its one
        value).
      Bars are stacked by human label (meme / not a meme / unlabeled) so the classes can be told
      apart, the x axis spans the metric's range over the whole video so charts of different
      selections are comparable, a criterion's threshold is drawn as a line, the selected values
      are marked when there are few of them, and the chart is accompanied by the count, min, max,
      mean and median of what it shows. It updates as the selection or the labels change.
- [ ] AC20a: **Zooming the histogram.** A vertical two-finger scroll on the chart (a pinch too)
      zooms the x axis in or out around the pointer, scrolling up zooms in; a horizontal two-finger
      scroll pans while zoomed. The visible window stays inside the metric's whole range and is never
      narrower than 1/2000 of it. Bars, the y axis and the counts shown follow the visible window
      (values outside it are not counted into the edge bins), a "Reset zoom" button appears while
      zoomed, and the title says what window is shown and how many frames are in view. The zoom
      persists while the selection or filters change, and resets when another metric is chosen. The
      page does not scroll or zoom while the pointer is over the chart.
- [ ] AC20: **Filtering from the histogram.** Dragging across the histogram selects a range of bins
      (a plain click selects one bin) and sets that metric's min/max in the strip filters (AC14),
      so the strip shows only the frames whose value falls in the range; other filters stay as they
      are and combine with it. The range is snapped to bin edges and shown as a shaded band with its
      limits on the chart. The charted metric's own range does not remove bars (the bars outside it
      are drawn dimmed on top of the rest of their bin but keep their label colours, and the counts
      and statistics cover only the frames inside),
      so the range can still be seen and changed on the chart; every other filter applies fully. Double-clicking the chart or a "Clear range" button removes the range, and editing the
      min/max boxes in the strip filters updates the shaded band.
- [ ] AC21: **Copy frame locator.** A button (and the C key) beside the mark buttons copies to the
      clipboard where the selected frame is: its video id, format id, timestamp and frame index, as
      `video=<id> format=<format id> ts=<seconds, 3 decimals> frame=<index>`. With several frames
      selected it copies one such line per frame, in frame order. The button is inactive when
      nothing is selected, shows how many locators it will copy, and confirms after copying.
- [ ] AC22: Offline tests cover the server's frame, thumbnail and label endpoints against a small
      synthetic video and a temp dataset directory. The page's own JavaScript is verified by hand
      and the result recorded in the Changelog.

## Out of Scope

- Precise mode (selecting a meme's start and end and labeling every frame in it).
- Choosing the final classifier or its thresholds (a later spec); this one only displays scores and
  filters on them.
- Auto-marking frames from a classifier: the human label is only ever set by the user.
- Multiple users, authentication, remote access.
- Labeling local video files.
- Editing a dataset's video identity.

## Technical Notes

- Flask serves the page and the API. It is the lightest framework that gives `flask run --debug`
  (reload on Python changes), and the work here is blocking OpenCV decoding, so async (FastAPI)
  adds nothing. Flask is in the optional `labeling` group with PyYAML. The page is one static HTML
  file with inline JS and CSS, read on every request so a browser refresh picks up edits.
- `labeler.sh` at the project root runs `flask --app tools.labeling.wsgi:create_app run --debug
  --no-reload` under `watchfiles`, which restarts it on any Python change (Flask's own reloader
  doesn't notice new files), with the video and options passed in environment variables; `python -m tools.labeling` stays as
  the plain launcher without reload.
- Exact indices and timestamps need a sequential decode (dataset AC4). Likely approach: a first
  pass over the file records every frame's presentation time and writes thumbnails for the strip
  to a cache under `.runtime/`; full frames are then decoded on request by reading forward from a
  nearby position and checking the index, because seeking alone can land on a different frame.
  A long video needs a progress indicator on that first pass.
- A strip at 3 fps of an hour-long video is ~10,800 rows, so it must be virtualised (only rows near
  the viewport exist in the DOM). Using `sample_frames`'s step rule means the strip rows match what
  the pipeline scans, so a classifier evaluated on the dataset is judged on those same frames.
- Frames are served as JPEG at the video's own resolution; thumbnails smaller.
- Stepping is by native frame even though the strip shows only the scanned frames, because a card
  lasts only ~10 frames and the scan can skip it entirely (ADR 008, the sampling gap); the labeler
  must let you mark a card the scan would miss.

- Scoring every scanned frame of an hour-long video at 3 fps is ~10,800 frames at about 0.5 ms
  each (ADR 008), so it adds seconds to the first pass. Scores are kept per criterion so adding
  one doesn't redo the others.
- Filtering can be done in the page over the cached scores (no round trip per change); the server
  only has to serve the score table.

## Open Questions

Resolved by the user (2026-10-07):

- Q1: Package module or script? **Dev tool outside the package**, so GitHub Actions builds don't
  include it or its dependencies — AC1, AC11.
- Q2: Overview? **A scrollable vertical timestrip of frames to select and edit labels** — AC3, AC5.
- Quality: **a low-quality video is fine** — AC2.

- Q3: Strip density? **Every frame the classifier sees (3 fps by default)** — AC3.

## Changelog

- 2026-10-07: Drafted together with [labeled-video-dataset](labeled-video-dataset.md) at the user's
  request. Standard mode only.
- 2026-10-07: The user answered the open questions: dev tooling outside the package, a vertical
  scrollable timestrip for selecting and editing labels, low-quality video, timestamps taken from
  the frames. Spec updated; Q3 added. Status `draft`, awaiting the user's go-ahead.
- 2026-10-07: The user asked that the strip show every frame being classified (3 fps by default,
  same as the scan) instead of a fixed 0.5 s step. AC3 and the technical notes updated; Q3 resolved.
- 2026-10-07: The user asked for classifier info in the UI (verdict and a score per criterion) and
  filtering on it. Added AC12–AC14 (info display, a criteria registry, filters including
  false-positive/miss views), renumbered the test criterion to AC15, and added a user-story clause.
  Status `draft`.
- 2026-10-07: The user said go. Implemented in `tools/labeling/` (`dataset.py`, `criteria.py`,
  `index.py`, `server.py`, `page.html`, `__main__.py`); run `python -m tools.labeling <url-or-id>`.
  Criteria registry: `band`, `texture`, `margin_luma`, `hue_consistency`. Server-side behaviour
  is covered by `tests/test_labeling_server.py` (8 tests). Ran it for real on `FtU4MuksCzE`
  (format 602, 256x144, 12.5 fps, 37,816 frames, 9,454 strip rows at step 4, indexed in ~9 s; the
  strip's effective rate is 3.125 fps because of the step rule). **Not verified yet:** the page's
  JavaScript was only syntax-checked (the Chrome extension wasn't connected), so AC15 stays
  unchecked and the status stays `in-progress` until the page has been used by hand.
- 2026-10-07: The user asked to select multiple frames by holding shift. Added AC15 (shift-click
  range and Cmd/Ctrl-click toggle in the strip, one bulk mark request; Shift+arrows keep their
  1 s step); the test criterion is now AC16. The shift-click range works on strip rows, since
  those are the frames the classifier sees.
- 2026-10-07: The user asked to also mark "not_meme". Added AC16 (a second human label with key X,
  stored in the dataset's `not_memes`, with its own filter value); the test criterion is now AC17.
- 2026-10-07: The user asked for a dev server that reloads on source changes and chose Flask. The
  server moved from `http.server` to Flask (`create_flask_app`), `labeler.sh` starts it with
  `flask run --debug`, Flask joined the `labeling` extra, and the host check now compares host
  names (any port) because the port is the CLI's choice. AC17 added; tests are now AC18.
- 2026-10-07: Added `labeler-run.sh`: `./labeler.sh FtU4MuksCzE --fps 3 --port 8765` (the settings
  used so far), where a leading video id/URL replaces the default and any other options are
  passed through.
- 2026-10-07: The user asked to provide the video URL in the UI. Added AC18 (an "Open video"
  control with the list of existing datasets, background load with progress, switch when ready,
  startup without a video); tests are now AC19. The server now holds a `Workspace` (current
  labeler, load status) instead of a single labeler.
- 2026-10-07: The user refined the control: a button that opens a modal where the URL/id is
  pasted, then shows the thumbnail, title and other general info plus the list of downloadable
  formats, and loading the selected one. AC18 rewritten (look-up step with `/api/inspect`, format
  list, dataset-pinned format, last video reopened on a dev-server restart).
- 2026-10-07: The user set the format preselection rule: at least 25 fps, then the smallest
  resolution, then not AV1 (`preferred_format` in `dataset.py`, returned as `preselected` by the
  look-up). Each rule only breaks ties of the previous one.
- 2026-10-07: The user asked for a dropdown of processed videos. Added one under the top bar
  (videos with a dataset, with counts; the open one is marked and disabled); choosing one opens it in
  its recorded format and shows the load progress in the modal.
- 2026-10-07: The user asked to move the processed-videos dropdown into the open-video modal. It
  replaces the modal's clickable list (and the top-bar dropdown); picking a video fills the id field
  and runs the look-up, so its details and recorded format show before Load.
- 2026-10-07: The user wanted Esc to deselect everything, not just the range. Esc now leaves no
  frame selected (AC15): no strip highlight, an empty large view, mark keys inactive; arrows resume
  from the last frame.
- 2026-10-07: The user asked for a histogram view next to the frame view, starting with the
  classifier criteria's scores: all frames when nothing is selected, only the selection otherwise.
  Added AC19 (metric list, stacked by human label, shared x range, threshold line, stats); the test
  criterion is now AC20.
- 2026-10-07: The user asked to select a range on the histogram to filter frames. Added AC20 (drag
  a bin range, it sets the metric's strip filter; shaded band, clear by double-click or button);
  the test criterion is now AC21. The chart keeps showing all frames/the selection so the range
  stays visible against the whole distribution.
- 2026-10-07: The user asked for a button that copies the frame locator (video id, format id,
  timestamp and index; one line per frame for a multi-selection). Added AC21; the test criterion is
  now AC22. Shortcuts with Ctrl/Cmd/Alt held are no longer taken by the page, so the browser's own
  Cmd+C still works.
- 2026-10-07: The user asked for a small reset button on each filter line that resets only that
  filter. Added to AC14 (human label, classifier and each criterion's min/max; disabled while a
  filter is at its default).
- 2026-10-07: The user wanted the histogram to show only filtered data. With no frame selected it
  now charts the frames the strip shows (AC19). The charted metric's own range is the exception: its
  excluded bars stay as faded ghosts so the range can still be seen and changed (AC20).
- 2026-10-07: The user reverted the x-axis auto-fit and asked for zooming instead, with the Mac
  trackpad two-finger scroll. Added AC20a: scroll zooms around the pointer (up = in), horizontal
  scroll pans, a pinch zooms too, "Reset zoom" restores the whole range. Dragging a range to filter
  works on the zoomed window, so a fine range can be set after zooming in.
- 2026-10-07: The user noted that the dimmed bars outside the range lost the label colours. They are
  now stacked by label like the others (meme gold, not a meme blue, unlabeled grey), at 30 % opacity,
  on top of the in-range part of each bin (AC20).

- 2026-10-07: Checked where the criteria come from. `band`, `texture` and the verdict call the
  production `HeuristicClassifier`; the margin geometry is now imported from it instead of copied;
  `band`'s threshold is read from the classifier; and a criterion's cache key now also covers what
  it depends on (the classifier's source, the margin helper and its geometry), so editing production
  scoring recomputes the cached `band`/`texture` scores instead of leaving them stale.
- 2026-10-07: The criteria moved out of the tool into the main code (see
  [classifier-criteria](classifier-criteria.md)): AC13 rewritten (no registry or scoring code in
  the labeler; verdict and thresholds from `HeuristicClassifier()`), AC17 and the dev-server note
  updated (`labeler.sh` now runs Flask under `watchfiles` so a new criterion file restarts it).
- 2026-10-07: Frames 0 to ~127 of H.264 videos in format 269 failed with "could not load frame N":
  the seek to those frames lands on the first restartable frame (128 in the two videos checked),
  past the target. The frame reader now decodes from the start when a seek can't get that early
  (AC8: the frame shown is the frame the index names). Checked 16 frames, early, late and in jumping
  order, against a sequential decode on `FtU4MuksCzE` format 269: all identical.
- 2026-10-07: The user asked for a shortcut to select all. A selects every row the strip shows
  (AC15), so it respects the filters; Cmd/Ctrl+A is left to the browser.
