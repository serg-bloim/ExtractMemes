# 013 — Publish the Docker Image via GitHub Actions on Tag Push

**Date:** 2026-09-17
**Status:** Accepted

## Context

[ADR 012](012-docker-image.md) added a `Dockerfile` for running ExtractMemes as a container. The
repo is being pushed to GitHub (by the human, outside this session). The next step is building
and publishing that image automatically so a tagged release always has a corresponding image,
without anyone building it by hand.

## Decision

Add `.github/workflows/docker-publish.yml`, triggered on push of tags matching `v*` (e.g. `v0.1.0`):

- Builds the root `Dockerfile`.
- Pushes to the **GitHub Container Registry** (`ghcr.io/<owner>/<repo>`), authenticating with the
  workflow's automatic `GITHUB_TOKEN` — no registry secrets to create or rotate.
- Tags the image with the semver version (`1.2.3`), the `major.minor` shorthand (`1.2`), and
  `latest`, via `docker/metadata-action`.
- Runs only on tag pushes, not on every commit to a branch — untagged commits don't get an image.

## Options Considered

- **Docker Hub** instead of GHCR — rejected for now; it requires creating a Docker Hub account and
  storing a username/access-token pair as repo secrets. GHCR needs zero setup beyond enabling
  GitHub Actions and (once, in the repo's Package settings) making the resulting package public if
  it should be pullable without auth. Revisit if the user specifically wants Docker Hub.
- **Build on every push to `main`** — rejected; ties image publishing to release tags so the image
  version always matches a real release, matching how the project already versions itself
  (`pyproject.toml`'s `version`).
- **Multi-arch build (amd64 + arm64)** — deferred; adds build time and complexity `docker/
  build-push-action` supports via `platforms:`, but not needed until someone asks for arm64
  (e.g. Apple Silicon hosts, Graviton).

## Consequences

- Tagging a commit `vX.Y.Z` and pushing the tag is now the release mechanism for the Docker image;
  forgetting to push the tag means no image gets built.
- The GHCR package defaults to private; the repo owner needs to make it public once (Package
  settings → Change visibility) if anonymous `docker pull` should work.
- `pyproject.toml`'s `version` isn't currently read by the workflow — the git tag is the sole
  source of the image version. If these ever need to be kept in sync, that's a separate decision.

## References

- [ADR 012 — Package ExtractMemes as a Docker Image](012-docker-image.md)
