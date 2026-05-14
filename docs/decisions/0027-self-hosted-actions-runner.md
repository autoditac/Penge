# 0027 — Self-hosted GitHub Actions runner on Ubuntu KVM VM

- **Status:** Accepted
- **Date:** 2026-05-14
- **Deciders:** @autoditac
- **Tags:** infra, ci

## Context and Problem Statement

All GitHub Actions CI jobs were failing immediately with the error:
> "The job was not started because recent account payments have failed or your spending limit needs to be increased."

The repository is private and hosted under a personal GitHub account. Actions minutes on private repositories consume the free-tier quota; once exhausted or when billing fails, all jobs are blocked. The team cannot merge PRs or validate changes without working CI.

## Decision Drivers

- CI must be available without depending on GitHub-hosted minutes billing.
- Workflows use `services: postgres`, `sudo apt-get`, PGDG apt repos, and `tesseract-ocr` — all Ubuntu-specific tooling.
- The runner host (`192.168.2.238`, CentOS Stream 8) cannot run the workflows natively due to OS mismatch.
- A containerized runner (Docker-in-Docker) cannot cleanly handle `services:` blocks that inject sidecar containers.
- An Ubuntu 24.04 KVM VM on the existing host provides native apt, Docker CE, and full service container support.

## Considered Options

1. **GitHub-hosted runners (ubuntu-latest)** — current/default
2. **Native runner on CentOS host** — runner binary on `192.168.2.238` directly
3. **Containerized runner (rootless podman)** — `myoung34/github-runner` image
4. **Ubuntu 24.04 KVM VM on CentOS host** — runner binary inside Ubuntu guest

## Decision

We chose **Option 4** (Ubuntu 24.04 KVM VM), because:

- All existing workflow steps work unchanged (apt, PGDG, tesseract, Docker CE).
- `services:` blocks work natively with Docker CE installed inside the VM.
- No billing dependency on GitHub-hosted minutes.
- The CentOS host has KVM support, 14 GB RAM, and a 200 GB LVM volume — sufficient for a small runner VM.
- The Ubuntu base cloud image provides a reproducible, well-understood environment.

## Consequences

### Positive

- CI is no longer gated by GitHub Actions billing.
- All existing workflow files need only a one-line `runs-on:` change.
- Runner is persistent (systemd service inside VM, survives reboots).
- Ubuntu VM is familiar; adding new apt dependencies in workflows is straightforward.

### Negative

- Runner availability depends on home-lab uptime (`192.168.2.238`).
- No auto-scaling: if multiple jobs queue simultaneously they execute serially.
- VM consumes ~2 GB RAM and ~5 GB disk permanently on the host.
- Re-registration requires a new registration token (short-lived); a PAT with `repo` scope or fine-grained "Administration: Write" can automate this via `config.sh --pat`.

### Neutral

- Runner version must be manually updated (or a cron job added) when new versions of `actions/runner` are released.
- The runner is registered with labels `self-hosted, linux, x64, penge, ubuntu-vm` — all workflow files use the `penge` label as the selector.

## Alternatives in detail

### Option 1 — GitHub-hosted runners

Simplest default. Blocked by billing failure on private repos. Acceptable for public repos or with a paid plan, but not reliable for this setup.

### Option 2 — Native runner on CentOS host

Tried and abandoned. The CentOS 8 system lacks `tesseract-ocr`, uses `dnf` not `apt`, and PGDG apt repo steps cannot run. Adapting all workflows to be OS-agnostic would require substantial ongoing maintenance.

### Option 3 — Containerized runner (rootless podman)

Runner `myoung34/github-runner` works well for simple jobs but cannot run `services:` blocks that require Docker daemon to start sidecar containers. The `ci.yml` pytest and alembic-roundtrip jobs both need a Postgres service container.

## Links

- [actions/runner v2.334.0](https://github.com/actions/runner/releases/tag/v2.334.0)
- [myoung34/github-runner](https://github.com/myoung34/docker-github-actions-runner) — Option 3, not chosen
- [GitHub docs: self-hosted runners](https://docs.github.com/en/actions/hosting-your-own-runners/managing-self-hosted-runners/about-self-hosted-runners)
- Runner host: `192.168.2.238` (`nederby.eigmueller.de`), VM: `192.168.122.50`
- VM disk: `/data/vms/gh-runner-ubuntu.qcow2` (overlay on Ubuntu 24.04 cloud image)
