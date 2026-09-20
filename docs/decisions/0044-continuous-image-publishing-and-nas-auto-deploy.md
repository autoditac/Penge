# 0044 — Continuous image publishing and NAS auto-deploy

- **Status:** Proposed
- **Date:** 2026-09-20
- **Deciders:** @autoditac
- **Tags:** infra, security

## Context and Problem Statement

ADR-0034 deliberately rejected publishing container images on every merge to
`main`, to "avoid unreviewed deployment artefacts": images were only pushed to
GHCR when a GitHub Release was published. In practice this means the
`container-images` job in `.github/workflows/ci.yml` builds every merge with
`push: false` and discards the result — a plain merge to `main` produces no
deployable artifact.

The NAS instance (`penge.eigmueller.de`) runs the API from a hand-built
`localhost/penge/api:dev` image, transferred with `podman save | ssh | podman
load` and restarted manually. `podman-auto-update.timer` is enabled on the NAS
but is a no-op: the quadlet has no `AutoUpdate=registry` label and the image
reference is local, not a registry pull. Every merge that changes the API
(e.g. #227) has required a manual rebuild-and-restart on the NAS, which is
slow, error-prone, and easy to forget.

Every merge to `main` already passes the full CI suite (pytest, dbt build,
Alembic round-trip, container image build verification, dependency review,
and PR review including a Copilot review with all threads resolved). Given
this pre-merge review bar, we re-evaluate ADR-0034's assumption that only
*release* merges are "reviewed" — regular merges to `main` are equally
reviewed, they just aren't tagged as a release.

## Decision Drivers

- Reduce the operational toil and error surface of manual NAS deploys (#227).
- Keep every image traceable to a reviewed, CI-green commit.
- No registry secrets in the repository; no real financial data ever crosses
  a build context (unchanged from ADR-0034).
- Reuse the existing release-time GHCR publish/SBOM/attestation pattern
  instead of inventing a second one.
- Prefer the NAS's existing `podman-auto-update.timer` machinery over adding
  a bespoke deploy runner or webhook receiver.
- Rollback must stay possible without re-triggering CI (pin the quadlet to
  an immutable `:<commit-sha>` tag, temporarily overriding auto-update).

## Considered Options

1. **Keep release-gated publishing only** — no CI change; deploy remains a
   manual, release-triggered process.
2. **Publish `:main` and `:<sha>` tags to GHCR on every merge to `main`**,
   and switch the NAS quadlet to pull `ghcr.io/autoditac/penge/api:main` via
   `podman-auto-update.timer` (`AutoUpdate=registry` label).
3. **Push-based deploy**: a self-hosted GitHub Actions runner on the NAS runs
   a `deploy` job after the images job, pulls the new digest, and restarts
   the quadlet.

## Decision

We chose **option 2**: publish images on every merge to `main` (this ADR,
implemented by #228 / the `publish-images` job in `ci.yml`), and switch the
NAS `penge-api` quadlet to `podman-auto-update.timer`-driven pulls from
GHCR (#229, follow-up PR).

`ci.yml` gains a `publish-images` job, gated with
`if: github.event_name == 'push' && github.ref == 'refs/heads/main'`, so it
never runs for `pull_request` events (forked PRs never gain
`packages: write`). It `needs` every other push-triggered job in `ci.yml`
that validates the *content of the published images*: lint, secret scan,
bootstrap smoke, the WebUI build, the Containerfile builds
(`container-images`), the Alembic migration round-trip the API runs on
startup, and pytest.

`dbt.yml`, `docs.yml`, `backup-roundtrip.yml`, and `mcp-evals.yml` also run
on the same push, as separate workflow files -- `needs:` cannot reach jobs
across workflow-file boundaries, and an earlier draft of this ADR/PR tried
to work around that by adding a job that polled the GitHub API for those
checks' status. That approach was dropped: it duplicated runner capacity
against the same constrained self-hosted pool the checks it waited on also
needed (risking contention or, in the worst case, deadlock), matched
check-runs by name and commit SHA alone (risking a stale match against an
earlier `pull_request` run of the same SHA), and required hand-maintaining
an ever-growing list of check names and path filters in lockstep with
unrelated workflow files. Instead, `publish-images` simply does not wait on
those four workflows: each validates an orthogonal subsystem -- dbt
models, the docs site, backup/restore scripts, MCP tool behaviour -- none
of which is part of the api/web container images' content, and each
already gates its own consequences independently (e.g. docs' GitHub Pages
deploy job already depends on its own build job succeeding). A failure in
any of them does not mean the just-built images are wrong.

`publish-images` mirrors `release.yml`'s `images` job: Buildx build,
SBOM request, GHCR push, and a build-provenance attestation for the pushed
digest. Tags are `:main` (moving, "latest known-good") and `:<commit-sha>`
(immutable, used for rollback and for pinning the NAS quadlet).

The release workflow (`release.yml`) is unchanged: tagged releases still
additionally publish `<release-tag>` and `<commit-sha>` images with the same
attestation, for consumers who want a stable version number rather than
tracking `main`.

Follow-up work (#229) will update the NAS `penge-api.container` quadlet to
reference `ghcr.io/autoditac/penge/api:main` with `AutoUpdate=registry`, so
`podman-auto-update.timer` (already enabled, currently a no-op) resolves
`:main` to its current digest on each poll and restarts the container when
it changes. The `Image=` line intentionally stays on the moving `:main` tag
-- that is what gives `AutoUpdate=registry` something to compare against;
pinning it to a digest would disable auto-update entirely. The digest podman
actually pulled is always inspectable after the fact (`podman inspect
penge-api --format '{{.Image}}'`), so no separate record-keeping step is
needed for audit. Rollback (see Consequences below) uses the immutable
`:<commit-sha>` tag instead: editing `Image=` to a specific `:<sha>` and
restarting pins the container to that exact reviewed build until the
quadlet is switched back to `:main`. GHCR pull credentials for the NAS will
be a fine-grained PAT with `read:packages` only, stored in the podman system
auth file on the NAS -- never in the repository. This PR only adds the
publish side (`ci.yml`); no quadlet or NAS configuration changes are
included here, and the NAS remains on its current manual/local-image deploy
process until #229 lands. The WebUI is currently served as static files
from `/var/www/penge` by the host's own nginx, not from the containerized
image; bringing it onto the same registry-pull path is out of scope for that
issue and can be a later follow-up if desired.

## Consequences

### Positive

- Every merge to `main` produces a deployable, SBOM'd, attested image within
  minutes, without waiting for a release.
- The NAS converges to the latest `main` image automatically via existing
  `podman-auto-update` machinery — no new runner or webhook to maintain.
- Rollback is a one-line quadlet edit (pin to a prior commit-sha tag) plus
  `systemctl restart`, with no rebuild needed.
- Release publishing keeps working unchanged for anyone tracking version
  tags instead of `main`.

### Negative

- `main` now always has a corresponding published image, increasing GHCR
  storage/quota usage over time (mitigated by GHCR's default retention and
  the option to prune old `:<sha>` tags later).
- The NAS PAT is a new secret to rotate and audit outside the repository.
- Auto-update means a merge to `main` reaches production without an
  explicit human "go" — mitigated by the existing pre-merge review bar
  (CI green + Copilot review threads resolved) being the actual gate now,
  matching how ADR-0034's "reviewed artefact" concern is already satisfied
  before merge.

### Neutral

- This supersedes ADR-0034's specific claim that "Penge currently follows a
  release workflow with explicit review and merge gates" as the sole
  trustworthy publish trigger; ADR-0034's Containerfile/SBOM/provenance
  design otherwise stands unchanged.

## Alternatives in detail

### Keep release-gated publishing only

Simplest, matches ADR-0034 exactly, but leaves the operational gap open
indefinitely (issues #227 and #229) — deploys stay manual and error-prone,
which is the problem this ADR exists to fix.

### Push-based deploy via a self-hosted NAS runner

Most flexible (explicit deploy job, environment protection rules,
approval gates), but adds a new self-hosted runner to provision and secure
on the NAS, and a second CI/CD surface parallel to `podman-auto-update`.
Rejected for now given the NAS already has working auto-update timer
machinery that only needs a registry image to point at.

## Links

- [ADR-0034 Application container images in CI and releases](0034-application-container-images.md)
- [Container images runbook](../runbook/container-images.md)
- `.github/workflows/ci.yml` (`publish-images` job)
- `.github/workflows/release.yml`
- Issue #227, #228, #229
