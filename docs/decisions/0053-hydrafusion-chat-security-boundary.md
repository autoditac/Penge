# 0053 — Secure HydraFusion chat boundary and empty-mode feature gate

- **Status:** Proposed
- **Date:** 2026-10-04
- **Deciders:** @autoditac
- **Tags:** mcp, security, web, infra, chat

## Context and Problem Statement

Issue #345 is the first architecture and feasibility gate for the planned Penge chat surface in parent issue #341. The product goal is a private, explanation-first assistant that can answer household-finance questions using only the Penge MCP tool layer and must never read raw statements, credentials, or account data directly.

The architecture must satisfy several simultaneous constraints:

- separate GitHub and Copilot identities per operator;
- an explicit session-level enablement gate for any production chat feature;
- a local MCP boundary over stdio with an allowlist of read-only tools only;
- no ambient shell, filesystem, or default tool access;
- no fallback model if `PENGE_CHAT_MODEL=hydrafusion` is requested; and
- a way to prove the SDK shape and stream contract without exposing tokens or financial data.

The current repository already enforces the stronger design direction in ADR-0005 (LLM access via MCP only) and ADR-0023 (local stdio MCP server). This ADR sits on top of that foundation and addresses the app-level chat runtime and security boundary.

## Decision Drivers

- Security: raw financial data must never leave the operator-controlled process.
- Privacy: separate GitHub and Copilot accounts are mandatory, and no shared household credentials are supported.
- Determinism: no LLM may invent numbers or bypass the typed tool surface.
- Auditability: every tool call and streamed event must be traceable and redacted.
- Simplicity: the first production chat surface is intentionally disabled until external entitlement is proven.
- Compatibility: the implementation matches the official current `@github/copilot-sdk` backend-services guidance for `mode: "empty"` and per-session user identity and tokens.

## Considered Options

1. **Server-side Copilot SDK with `mode: "empty"`, local stdio MCP allowlist, and feature-disabled default** — chosen.
2. **Shared GitHub/Copilot account with an ambient default tool set** — rejected.
3. **HTTP MCP transport or direct agent access to Postgres/DuckDB** — rejected.
4. **Fallback model path for HydraFusion requests** — rejected.

## Decision

We chose **Option 1**: the production chat feature is implemented as a strict SDK session contract anchored to the official backend-services pattern. The runtime requires:

- `@github/copilot-sdk@1.0.16` pinned exactly in `apps/mcp/package.json`;
- a session created with `mode: "empty"` and a per-user `gitHubToken` bound to the correct GitHub/Copilot identity pair;
- a local stdio MCP connection with an explicit tool allowlist; and
- an explicit production gate that rejects the feature until the correct HydraFusion entitlement is verified.

The app-level config contract is intentionally strict:

- `PENGE_CHAT_MODEL=hydrafusion` is accepted only as the requested model name in the application config;
- `PENGE_CHAT_FALLBACK_MODEL` must be completely unset;
- `PENGE_CHAT_ENABLE_PRODUCTION` must be explicitly `1` before any production session is allowed;
- `PENGE_CHAT_GITHUB_LOGIN` and `PENGE_CHAT_COPILOT_LOGIN` must differ; a shared account is rejected;
- the ambient tool list is fixed to `shell`, `filesystem`, and `default` and must be denied;
- no HTTP-based MCP transport is introduced.

In the current environment we cannot safely prove real HydraFusion entitlement without exposing or logging user tokens, so production activation remains disabled until that external gate is confirmed by the authenticated user and their Copilot plan. The repository therefore ships the contract, the synthetic harness, and the disable-by-default runtime checks without enabling the live feature.

## Consequences

### Positive

- No raw household-finance data leaves the local process boundary.
- The runtime matches the official backend pattern for multi-user server deployments.
- Tool access is explicit and auditable.
- The feature remains safe even when the exact HydraFusion entitlement is not yet available.
- The synthetic harness proves the stream contract and policy checks without using any real financial data.

### Negative

- The live HydraFusion feature stays disabled until the external entitlement check succeeds.
- The exact HydraFusion model ID is not a stable public contract in the backend SDK docs we can safely rely on from this environment.
- More setup work is required for every new session and tool.

### Neutral

- The product surface remains explanation-first and deterministic, rather than autonomous.
- The MCP tool registry stays the trusted source of data truth.

## Alternatives in detail

### Option 1: server-side SDK + `mode: "empty"`

This matches the official GitHub backend-services documentation: the SDK client runs in a shared process, the session holds user credentials per call, and tool access is explicitly allowed. It is the correct pattern for multi-user enterprise backends and avoids shared-account risk.

### Option 2: shared GitHub/Copilot account

Rejected because it violates the issue requirement and creates privacy and audit ambiguity. A single household account cannot represent two separate identities.

### Option 3: HTTP MCP or direct DB access

Rejected because the repository policy in ADR-0005 is explicit: raw data is accessed through the MCP layer only. Exposing an HTTP MCP port or any agent access path to Postgres/DuckDB would create a material privacy boundary break.

### Option 4: fallback model path

Rejected because the issue explicitly forbids fallback when `PENGE_CHAT_MODEL=hydrafusion` is requested. This would silently degrade the trust boundary and create model-selection drift.

## Links

- ADR-0005 — LLM access exclusively via MCP server with typed tools
- ADR-0023 — MCP server architecture (TypeScript skeleton)
- `apps/mcp/src/chat.ts`
- `apps/mcp/tests/chat.test.ts`
- Official GitHub Docs: backend services setup with `mode: "empty"` and per-user tokens
- Official GitHub Docs: GitHub Copilot SDK (`@github/copilot-sdk`)
