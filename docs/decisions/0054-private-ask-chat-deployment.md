# 0054 — Fail-closed deployment for private Ask Penge chat

- **Status:** Proposed
- **Date:** 2026-10-04
- **Deciders:** @autoditac
- **Tags:** mcp, web, infra, security

## Context and Problem Statement

The parent feature (#341) adds a private Ask Penge chat across separate architecture, MCP, backend, WebUI, and infrastructure workstreams.
The infrastructure work must define a reproducible NAS boundary without guessing contracts that belong to #343–#346 or exposing a partially integrated service.

The foundational security decision is reserved as ADR-0053 by #345.
This ADR covers only the deployment boundary and remains proposed until those contracts and authorized acceptance evidence exist.

## Decision Drivers

- No public MCP, Copilot runtime, database, metrics, or raw-tool listener.
- Immutable image deployment and reviewable rollback by digest.
- Rootless process isolation with secrets outside images and environment files.
- Separate user identities and encrypted OAuth links without transcript persistence.
- Fail-closed startup when source coverage, HydraFusion entitlement, or application contracts are unproven.

## Considered Options

1. **Deploy a moving image tag immediately** — enables automatic updates but is not reproducible.
2. **Guess the dependent application contracts** — appears complete but can weaken or bypass the intended security boundary.
3. **Commit non-loadable templates and readiness gates** — validates the boundary now and blocks deployment until exact contracts are integrated.

## Decision

We chose **non-loadable templates and readiness gates**.

The tracked rootless Quadlet uses an immutable digest placeholder, loopback-only publishing, read-only mounts, dropped capabilities, secret mounts, and a runtime-owned health-command placeholder.
It has a `.container.in` suffix, and the installer refuses to create a user unit while any contract token remains.

The active nginx configuration explicitly returns `404` for only `/ask` and `/ask/…`.
A separate non-loadable nginx template contains the OAuth trust-boundary and identity-header overwrite contract, but it cannot be enabled until exact base-path, callback, and streaming semantics are known.

The OAuth database role is likewise represented by a non-executable SQL template.
It permits only connect, schema usage, and row operations on the migration-owned OAuth-link tables after those identifiers are supplied; it grants no finance, analytics, MCP, transcript, or default privileges.

ADR-0053 fixes `@github/copilot-sdk` at `1.0.16`, Copilot mode `empty`, the exact model `hydrafusion`, separate per-user identities, process-local stdio MCP, and no default tools or fallback.
Production activation still requires external, privacy-safe entitlement evidence and the source-coverage startup contract.

## Consequences

### Positive

- The repository cannot accidentally install or start an unresolved chat unit.
- Public routes remain closed while dependent contracts are absent.
- Image, secret, database, and identity boundaries are reviewable before NAS changes.
- Later integration failures become explicit CI/readiness failures instead of permissive defaults.

### Negative

- No chat image is built or deployed by this change alone.
- Live HydraFusion, two-user isolation, streaming, cancellation, and reconnect acceptance remain blocked.
- A follow-up is required after #343–#346 publish their exact contracts.

### Neutral

- Existing API and WebUI deployment continue using their current system-level Quadlets.
- The chat service intentionally uses a separate rootless user-service ownership model.

## Alternatives in detail

### Deploy a moving image tag immediately

This would align with existing automatic image updates but violate the immutable-image requirement and make rollback evidence ambiguous.

### Guess the dependent application contracts

This would encode unverified routes, environment names, health commands, table names, and package commands.
Such guesses could pass shallow tests while producing an insecure or non-functional deployment.

## Links

- Parent feature: #341
- Infrastructure issue: #342
- Foundational architecture and feasibility: #345 / ADR-0053
- MCP source coverage: #344
- Chat backend: #346
- Ask Penge WebUI: #343
- [Private Ask Penge deployment runbook](../runbook/private-ask-chat.md)
