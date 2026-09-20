# 0044 — Continuous image publishing and NAS auto-deploy

- **Status:** Accepted
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
  a previously-recorded manifest digest, temporarily overriding
  auto-update).

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
(immutable, useful for pinning to a specific reviewed commit). The NAS
rollback path implemented in #229 pins to the recorded manifest digest
instead (see the "Update (implementation, #229)" note below), since it is
exact and does not depend on a `release.yml`-only tag existing for the
build in question.

The release workflow (`release.yml`) is unchanged: tagged releases still
additionally publish `<release-tag>` and `<commit-sha>` images with the same
attestation, for consumers who want a stable version number rather than
tracking `main`.

Follow-up work (#229) updates the NAS `penge-api.container` quadlet to
reference `ghcr.io/autoditac/penge/api:main` with `AutoUpdate=registry`, so
`podman-auto-update.timer` (already enabled, previously a no-op) resolves
`:main` to its current digest on each poll and restarts the container when
it changes. The `Image=` line intentionally stays on the moving `:main` tag
-- that is what gives `AutoUpdate=registry` something to compare against;
pinning it to a digest would disable auto-update entirely. An
`ExecStartPost` step resolves the container's actual running image
(`podman inspect penge-api --format '{{.Image}}'`, then `podman image
inspect <that id> --format '{{.Digest}}'`) and logs it to the unit's
journal on every start, so the digest that was actually deployed is always
recorded, not just inspectable after the fact. Rollback (see Consequences
below) pins `Image=` to that recorded manifest digest
(`ghcr.io/autoditac/penge/api@sha256:<digest>`) instead of a tag: a digest
is immutable and exact, whereas a `:<commit-sha>` tag from `release.yml`
would only exist for tagged releases and could not point at an arbitrary
`main` build. Editing `Image=` to the pinned digest and restarting freezes
the container on that exact build (and incidentally halts auto-update,
since a digest never changes) until the quadlet is switched back to
`:main`.

**Update (implementation, #229):** GHCR packages inherit their visibility
from the repository, and `autoditac/Penge` is public, so
`ghcr.io/autoditac/penge/{api,web}` are pullable anonymously (verified with
an unauthenticated `skopeo inspect`). The NAS therefore needs **no** GHCR
credential for this pull path -- the fine-grained-PAT plan below was the
default assumption before the images existed and publish visibility could
be checked; it is kept here as the documented fallback if the repository or
its packages are ever made private. The WebUI is currently served as static
files from `/var/www/penge` by the host's own nginx, not from the
containerized image; bringing it onto the same registry-pull path is out
of scope for #229 and can be a later follow-up if desired.

**Update (implementation, #273):** The deferred WebUI follow-up is complete.
The NAS now runs the published `penge/web:main` image through a
`penge-web.container` quadlet with the same registry auto-update, health-check,
digest-log, and rollback properties as the API container.
The host nginx remains the TLS and OAuth boundary and proxies authenticated SPA
requests to the WebUI container over a loopback-only port.
The WebUI Containerfile sets its overridable production build argument
`VITE_PENGE_API_URL` to `https://penge.eigmueller.de`, so browser API requests
return through that same authenticated host instead of targeting localhost.
This removes the separate, manually copied `/var/www/penge` deployment path.

The self-hosted runner also accumulated orphaned Buildx builder containers and
volumes after jobs did not complete their action post-hooks, eventually filling
the runner VM disk.
Both CI and release workflows now include an explicit `if: always()` teardown
step for every Buildx setup so normal failed jobs remove their builder state
before the runner accepts more work.
Each matrix job also uses a run-unique `DOCKER_CONFIG` directory under `/tmp`.
The runner services share an operating-system user, so this prevents one
concurrent job's login-action cleanup from removing another job's GHCR
credentials during provenance upload.

## Consequences

### Positive

- Every merge to `main` produces a deployable, SBOM'd, attested image within
  minutes, without waiting for a release.
- The NAS converges to the latest `main` image automatically via existing
  `podman-auto-update` machinery — no new runner or webhook to maintain.
- Rollback is a one-line quadlet edit (pin `Image=` to a prior digest
  recorded in the unit's journal log) plus `systemctl restart`, with no
  rebuild needed.
- Release publishing keeps working unchanged for anyone tracking version
  tags instead of `main`.

### Negative

- `main` now always has a corresponding published image, increasing GHCR
  storage/quota usage over time (mitigated by GHCR's default retention and
  the option to prune old `:<sha>` tags later).
- GHCR package visibility (public, inherited from the public repository) is
  a soft dependency for anonymous NAS pulls; if it is ever tightened, a PAT
  must be provisioned before the next auto-update poll (see the
  implementation note above).
- Auto-update means a merge to `main` reaches production without an
  explicit human "go" — mitigated by the existing pre-merge review bar
  (CI green + Copilot review threads resolved) being the actual gate now,
  matching how ADR-0034's "reviewed artefact" concern is already satisfied
  before merge.
- Auto-update replaces the image only; it never runs Alembic. A PR that
  needs its migration applied before its API changes work correctly must
  not rely on deploy ordering -- see "Migration coordination" in the
  [NAS deploy runbook](../runbook/nas-deploy.md) for the expand/contract
  and manual-migration-before-merge contract this requires.

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
- [NAS deploy and rollback runbook](../runbook/nas-deploy.md)
- `.github/workflows/ci.yml` (`publish-images` job)
- `.github/workflows/release.yml`
- `deploy/nas/penge-api.container` (tracked quadlet)
- `deploy/nas/penge-web.container` (tracked quadlet)
- `deploy/nas/penge.eigmueller.de.conf` (tracked host proxy)
- Issue #227, #228, #229, #273
