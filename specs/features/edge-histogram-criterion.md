---
title: "Edge Histogram Criterion"
status: implemented
created: 2026-10-07
updated: 2026-10-07
author: ""
depends-on: ["classifier-criteria", "edge-black-criterion", "criteria-evaluation"]
---

# Edge Histogram Criterion

## Problem Statement

A single number such as the share of near-black pixels on the edges cannot describe what the edges of
a glitch card look like: the mix of black, dark colour, mid-tones and white streaks. Comparing the
whole brightness distribution of a frame's edges with the average distribution of the labeled memes,
in units of how much that distribution varies among memes, separated memes from all other frames in
an experiment on the two labeled videos far better than any one-number criterion (a template taken
from the other video alone gave 0 missed memes and 3 false positives, which are glitch frames with no
card). The criterion needs a stored reference built from the labeled data.

## User Story

**Primary:**
As the developer improving the classifier, I want a criterion that measures how far a frame's edge
brightness distribution is from the average of the labeled memes, with the reference built from the
datasets by a tool, so that I can study it in the labeler and the evaluator and use it in rules.

## Acceptance Criteria

- [x] AC1: `extract_memes.criteria` provides `edge_histogram`: the frame's grayscale brightness
      histogram over the outermost 5% of the width on the left and right (the `edges()` strips of
      [edge-black-criterion](edge-black-criterion.md), pooled), in 16 equal bins over 0-255 and
      normalised to sum to 1, compared with the reference by
      `sqrt(mean(((h - mean) / (std + 1e-3 * mean(|mean|)))^2))` over the bins. 0 means the frame's
      histogram equals the memes' average; memes score around 1-2, ordinary frames mostly above 4.
- [x] AC2: The reference (`mean` and `std` per bin, the number of frames and the videos it came from)
      is a JSON file shipped in the package (`extract_memes/criteria/data/edge_histogram.json`, listed
      as package data so the installed package and the image contain it). Importing the criterion
      reads nothing; the file is read on the first score, and a missing or malformed file raises an
      error that names the file and the tool that builds it.
- [x] AC3: A criterion can declare data files (`@criterion("name", data=("file.json",))`); its
      `fingerprint()` then includes their contents, so cached scores are recomputed when the
      reference is rebuilt. Fingerprints of other criteria are unchanged by this.
- [x] AC4: `python -m tools.evaluation.build_template edge_histogram` rebuilds the reference from the
      frames inside the marked meme windows of every dataset in `data/datasets/` (the ground truth of
      [criteria-evaluation](criteria-evaluation.md) AC1), using the same feature function the
      criterion uses, and writes the JSON file. The file in the repo is built this way from the
      current datasets.
- [x] AC5: The score does not depend on the frame's resolution (scan size, like every criterion), and
      it appears in the labeler and evaluator without further wiring.
- [x] AC6: Offline tests cover the feature (bin counts, edges only), the distance (0 at the mean, grows
      with distance, per-bin scaling), loading and the error for a missing file, the data-file
      fingerprint, and the template builder on synthetic frames. No test needs the real videos.

## Out of Scope

- Adopting the criterion in the production classifier.
- Other spectra (row spectrum, 2D Fourier) and per-colour-channel histograms; they can be added the
  same way if this one proves insufficient.
- Fixing the glitch-only frames (no card) that every edge-based score calls memes.

## Technical Notes

- Experiment (scratch, 2026-10-07; template from the other video's memes, 5% edges): histogram
  z-distance gave 0 missed memes and 3 false positives; without those 3 glitch-only frames memes were
  at most 1.96 and the nearest other frame 2.73. Plain L1 or cosine distances were much worse; the
  per-bin scaling is what makes it work.
- The shipped reference is built from all labeled memes, so scores on those videos are optimistic;
  judge it on a video that was not used for the reference.
- Adds package data (`[tool.setuptools.package-data]`) but no dependency.

## Open Questions

None.

## Changelog

- 2026-10-07: The user asked to add the brightness-histogram distance (to the mean edge profile of the
  labeled memes) as a criterion. Wrote this spec and set it `in-progress`.
- 2026-10-07: Implemented `criteria/edge_histogram.py`, the `data=` declaration and its fingerprint in
  `criteria/__init__.py`, `tools/evaluation/build_template.py` (reference built from the 231 meme
  frames of the two datasets, `criteria/data/edge_histogram.json`) and package data in `pyproject.toml`
  (checked: a built wheel contains the JSON). `load_truth` in `tools/evaluation/data.py` lets the
  builder run before the reference exists. Tests: 435 passed. On the labeled videos
  `edge_histogram < 2.173` misses 0 memes and has 11 false positives: 8 are unlabeled memes in
  `5vGNfK5jL4U`/`FtU4MuksCzE`, 3 are glitch-only frames with no card. The reference includes these
  videos' memes, so the figure is optimistic.
