# 0006 — Trunk-based development with Conventional Commits and ADRs

- **Status:** Accepted
- **Date:** 2026-05-06
- **Deciders:** @autoditac
- **Tags:** infra

## Context and Problem Statement

Penge is a single-developer project intended to run for a decade. We need
a development flow that yields strong traceability (which change, why,
which decision, which release) without imposing the overhead of a
multi-team Git-flow process.

## Decision Drivers

- Traceability: future-me must be able to answer "why does this exist?"
  from the repo alone.
- Low ceremony: one developer, must not slow down day-to-day work.
- Automation: changelog and version bumps must be derivable from the
  history.
- Reversibility: ability to revert any single change cleanly.

## Considered Options

1. **Trunk-based development with Conventional Commits + ADRs + release-please** — short-lived branches off `main`, PR per change, semantic commits, automated changelog/version, ADRs for non-trivial decisions.
2. **Git-flow** — `develop`, `release/*`, `hotfix/*` long-lived branches.
3. **Direct commits to `main`** — no PRs, no review.

## Decision

We chose **Option 1: trunk-based + Conventional Commits + ADRs**.

- Short-lived feature branches named `<type>/<issue>-<slug>`.
- Every change goes through a PR, even for the sole maintainer, to get
  CI signal and a permanent diff record.
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/);
  `commitlint` enforces the grammar.
- Non-trivial decisions become ADRs under `docs/decisions/` (MADR template).
- Releases are cut by `release-please`, which derives versions and
  CHANGELOG entries from commit types.
- Branch protection on `main` requires PR + green CI + linear history.

## Consequences

### Positive

- Linear, bisectable history.
- Automated, accurate CHANGELOG and SemVer.
- ADRs capture intent that diffs cannot.
- Same workflow scales if a second contributor joins.

### Negative

- PR overhead for trivial single-line changes.
- Commit-message discipline required (mitigated by `commitlint` +
  `gitlint` pre-commit).

### Neutral

- We do not require signed commits in Phase 0; we will revisit when a
  signing key is configured (tracked separately).

## Alternatives in detail

### Git-flow

Rejected: designed for parallel release trains; adds branches we will
never use.

### Direct commits to `main`

Rejected: no CI gate, no review record, no changelog discipline,
incompatible with the traceability driver.

## Links

- `.github/PULL_REQUEST_TEMPLATE.md`
- `commitlint.config.cjs`
- `.github/workflows/ci.yml`
- Issue #6 (branch protection)
- Issue #26 (release-please)
