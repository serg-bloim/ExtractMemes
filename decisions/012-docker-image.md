# 012 — Package ExtractMemes as a Docker Image

**Date:** 2026-09-17
**Status:** Accepted

## Context

Running ExtractMemes requires Python 3.14, Node.js (for yt-dlp's JS runtime on YouTube
downloads), and — for `--classifier claude` — the authenticated `claude` CLI. Setting this up by
hand is friction for anyone who just wants to run the pipeline. A Docker image gives a
reproducible, portable runtime that bundles the interpreter and Node.js so `docker run` works
without a local Python/Node setup.

This is a packaging/deployment concern, not a change to pipeline behavior, so it does not have a
`specs/features/` entry with user stories and acceptance criteria — CLAUDE.md's ADR guidance
explicitly calls out "choosing ... a deployment platform" as ADR-worthy.

## Decision

Add a `Dockerfile` (and `.dockerignore`) at the project root that:

- Builds on a slim official Python 3.14 base image.
- Installs Node.js (required by yt-dlp's `js_runtimes` option for YouTube downloads; see ADR 006).
- Installs the project in non-editable mode via `pip install .` (runtime deps only — no `dev`
  extras, no test suite baked in).
- Sets the entrypoint to the `extract-memes` console script.
- Mounts-friendly: `downloads/` and `.runtime/` are left as plain directories under `/app` so a
  caller can bind-mount them for persistent output; nothing is written outside those two
  directories plus the video source itself.
- Does **not** install or configure the `claude` CLI. `--classifier claude` requires an
  authenticated `claude` CLI, which needs interactive login and a user's own credentials — out of
  scope for a base image. `--classifier heuristic` (the default) works out of the box.

## Options Considered

- **Bake `sample/` and `data/labeled_dataset/` into the image** — rejected; those are dev/test
  fixtures (`data/labeled_dataset/` is gitignored... actually tracked per ADR 008, but is only
  needed for classifier evaluation, not for running the pipeline). Keeping the image lean matters
  more than convenience for a use case (classifier eval) the image isn't meant to serve.
- **Multi-stage build to slim the final image** — deferred; `opencv-python-headless`,
  `static-ffmpeg`, and `yt-dlp` are the heavy dependencies and none benefit much from being built
  in a separate stage since they ship as wheels. Revisit if image size becomes a problem.
- **Bundle the `claude` CLI and require credentials at build time** — rejected; credentials don't
  belong in an image layer, and login is inherently interactive.

## Consequences

- `docker build` requires network access to pull the base image and PyPI packages.
- Users who need `--classifier claude` must install and authenticate the `claude` CLI themselves,
  either by running outside Docker or by extending this image in their own Dockerfile.
- Output directories (`downloads/`, `.runtime/`) should be bind-mounted by the caller if they want
  results to survive past the container's lifetime; otherwise they're ephemeral container state.

## References

- [ADR 006 — YouTube Downloads: Video-Only Formats, Node.js JS Runtime, Bundled ffmpeg](006-youtube-video-only-formats-and-download-toolchain.md)
- [ADR 007 — Consolidate Specs and ADRs as the Source of Truth for a From-Scratch Rebuild](007-documentation-consolidation-for-rebuild.md)
- `CLAUDE.md` — Code Conventions (external prerequisites: `claude` CLI, Node.js)
