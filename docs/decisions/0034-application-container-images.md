# 0034 — Application container images in CI and releases

- **Status:** Proposed
- **Date:** 2026-05-22
- **Deciders:** @autoditac
- **Tags:** web, infra, security

## Context and Problem Statement

Penge now has a modern WebUI app under `apps/web`, but CI only built the
TypeScript artefact.
There was no application container image, so deployment could drift from the
tested build and the release workflow's image/SBOM/provenance placeholder stayed
disabled.

We need a repeatable container boundary that is safe for a private finance app:
base images must be pinned, no local data may enter build contexts, CI must
verify image builds on every PR, and releases must produce traceable images.

## Decision Drivers

- Images must be reproducible enough for home-server deployment and review.
- No real financial data, backups, reports, statements, or local secrets may be
  sent into Docker build contexts.
- Base images and GitHub Actions must be pinned.
- Release images must be pushed to GHCR with SBOM and provenance support.
- The first image should be the WebUI; future app images should follow the same
  `apps/<name>/Containerfile` convention.

## Considered Options

1. **CI only runs `docker build`** — simple, but leaves release publishing,
   SBOMs, and provenance as manual work.
2. **Build and push on every `main` commit** — fast deployment path, but creates
   mutable images outside the release process.
3. **CI build verification plus release-time GHCR publishing** — test images on
   PRs and publish only when a release is cut.

## Decision

We chose **CI build verification plus release-time GHCR publishing**.

The WebUI image is defined by `apps/web/Containerfile`.
It uses a pinned Node build stage and a pinned unprivileged Nginx runtime stage.
The image serves the static Vite output on port `8080`.

CI runs a matrix job over application Containerfiles, currently:

```yaml
app: [web]
```

For pull requests, CI builds the image without pushing it.
For published releases or manual release workflow dispatch, the release workflow
pushes images to:

```text
ghcr.io/autoditac/penge/<app>
```

Each release image is tagged with the release tag (or a manual workflow tag) and
the commit SHA.
The release job also requests an image SBOM from Docker Buildx and emits GitHub
build-provenance attestation for the pushed digest.

## Consequences

### Positive

- Deployment images are now tested by the same CI surface as code changes.
- Release artefacts include a container image, SBOM, and provenance path.
- `.dockerignore` prevents private local data from entering build contexts.
- Future apps can opt into the same pipeline by adding
  `apps/<name>/Containerfile` and extending the matrix.

### Negative

- CI now depends on Docker Buildx working on the self-hosted runner.
- Release publishing requires GHCR package permissions.
- The WebUI runtime is static-only; API-backed features still need a future API
  service image.

### Neutral

- `compose.yaml` remains the local infra compose file.
  A production compose file with pinned GHCR digests should be added once the
  first deployment target is ready.

## Alternatives in detail

### CI only runs `docker build`

This would catch broken Containerfiles but would not create deployable artefacts
or supply-chain metadata.
Rejected because the release workflow already has the right permissions and
attestation intent.

### Build and push on every `main` commit

This is useful for continuous deployment, but Penge currently follows a release
workflow with explicit review and merge gates.
Rejected for now to avoid unreviewed deployment artefacts.

## Links

- [ADR-0033 Reporting-first React WebUI](0033-reporting-first-react-webui.md)
- [Container images runbook](../runbook/container-images.md)
- `apps/web/Containerfile`
- `.github/workflows/ci.yml`
- `.github/workflows/release.yml`
- Issue #200
