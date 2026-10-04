# 0053 — Isolated multi-user chat runtime with local MCP-only access

- **Status:** Accepted
- **Date:** 2026-10-04
- **Deciders:** @autoditac
- **Tags:** security, mcp, chat, infra

## Context and Problem Statement

Penge needs a household chat interface that keeps each household member isolated while giving them a safe, read-only path to their financial data. The platform already enforces an MCP-only policy for LLM access, but the chat layer introduces a second trust boundary: multiple users, OAuth identities, session lifetimes, and a local model SDK that must not leak finance data or allow agentic tool escape.

The new runtime therefore needs to be fail-closed: loopback-only HTTP, exact model binding to `hydrafusion`, no fallback, skew-resistant per-user sessions, and only a tiny allowlist of local MCP tools. Anything outside the local process boundary is denied or treated as unavailable.

## Decision Drivers

- Secure isolation across household members and OAuth identities.
- No direct access to finance tables from the chat service.
- Fail-closed behavior when the model, OAuth state, allowed tools, or readiness checks are unavailable.
- Read-only, auditable tool access through the existing Penge MCP server.

## Considered Options

1. **Strict local chat service + typed MCP gateway** — message routing stays inside the local host, exposes only a curated tool allowlist, and binds identity and token state to user-specific sessions.
2. **Direct model access with broad tool permissions** — simpler to start, but violates the repo’s security boundary and would expose finance-table access.
3. **Opaque chat proxy with no typed event contract** — easy to implement, but impossible to audit, validate, and safely cancel or isolate.

## Decision

We chose **Option 1: strict local chat service + typed MCP gateway**.

This service is intentionally limited to local loopback traffic, uses Google oauth2-proxy identity binding and per-user GitHub App OAuth, stores only encrypted and versioned refresh tokens, and uses a single exact model identifier: `hydrafusion`. The model runtime runs in `mode: "empty"` with fallback disabled; if HydraFusion is unavailable the service fails closed instead of falling back to another model or broader permissions.

The Penge MCP boundary remains strict and read-only. Only explicit, allowlisted tools can be invoked. Tool calls, stream events, state transitions, and cancellation reasons are validated with zod and constrained to a versioned event protocol so malformed events are rejected before they reach the SDK or the MCP process.

## Consequences

### Positive

- Cross-user chat sessions remain isolated by actor ID and session ownership.
- No finance-table direct access from the chat runtime.
- Local-only HTTP and local stdio MCP keep the runtime off the public network.
- The stream protocol supports cancellation, timeout, and malformed-event rejection.

### Negative

- The implementation is intentionally strict and requires more operational setup than a permissive runtime.
- If HydraFusion entitlement is missing, the chat service is unavailable until the exact feature is enabled.

### Neutral

- OAuth and token storage remain typed and versioned to allow future rollout without silent schema drift.

## Alternatives in detail

### Direct model access with broad tool permissions

Rejected: it would violate the MCP-only architecture decision and grant too much access to ambient finance data.

### Opaque event protocol

Rejected: it could not enforce strict ordering or reject malformed events before state changes occur.

## Links

- [ADR-0005](0005-llm-access-via-mcp-only.md)
- [ADR-0023](0023-mcp-server-architecture.md)
- [apps/chat/src/config.ts](../../apps/chat/src/config.ts)
- [apps/chat/src/runtime.ts](../../apps/chat/src/runtime.ts)
- [apps/chat/src/sdk.ts](../../apps/chat/src/sdk.ts)
