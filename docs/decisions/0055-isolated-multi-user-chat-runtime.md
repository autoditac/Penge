# 0055 — Isolated multi-user chat runtime

- **Status:** Proposed
- **Date:** 2026-10-04
- **Deciders:** @autoditac
- **Tags:** security, mcp, chat, oauth

## Context and Problem Statement

Issue #346 implements the production service boundary approved by the HydraFusion feasibility work in issue #345.
Two household members must be able to use their own GitHub and Copilot identities without sharing credentials, sessions, transcripts, or quotas.
The chat service must preserve [ADR-0005](0005-llm-access-via-mcp-only.md) and [ADR-0023](0023-mcp-server-architecture.md): finance evidence reaches the model only through bounded read-only Penge MCP tools over process-local stdio.

## Decision Drivers

- Bind every request to an immutable Google subject supplied by the trusted reverse proxy.
- Use a separate per-actor GitHub OAuth grant with state, PKCE, refresh, and key rotation.
- Fail closed unless the linked actor is entitled to the exact experimental model ID `hydrafusion`.
- Deny ambient tools, permissions, credentials, config discovery, and transcript storage.
- Propagate stop, disconnect, timeout, concurrency limits, and idle cleanup to Copilot and MCP child processes.
- Give the chat database role no finance-table privileges.

## Considered Options

1. **Loopback Node service with actor-scoped SDK clients and local MCP** — chosen.
2. **Shared household GitHub/Copilot identity** — rejected because it breaks credential and quota isolation.
3. **Network MCP or direct finance database queries** — rejected because it breaks the existing data boundary.
4. **Fallback model when HydraFusion is unavailable** — rejected because it changes reviewed behavior.

## Decision

`apps/chat` is a strict TypeScript service listening only on a configured loopback address.
The authenticated external browser origin is separate from the listener and must use HTTPS outside local development.
The external API base is a trailing-slash URL so reverse-proxy path prefixes survive OAuth callback construction; the path-free app origin independently owns the `/ask` redirect.
The reverse proxy must overwrite and supply `X-Penge-Auth-Issuer`, immutable Google `X-Penge-Auth-Subject`, and a mounted-secret-backed `X-Penge-Proxy-Secret`; direct or ambiguous headers are rejected.

Each pseudonymous actor completes GitHub OAuth with one-time state and S256 PKCE.
The database stores only an HMAC state lookup and an encrypted versioned state envelope, never raw state or a plaintext verifier.
Access and refresh tokens use AES-256-GCM envelopes carrying a key ID.
A mounted versioned keyring retains old keys for decryption while one current key encrypts new and refreshed credentials.
Per-actor PostgreSQL advisory locks serialize refresh, relink, status, and unlink operations across service processes so rotating refresh tokens cannot be redeemed concurrently or overwrite a newer link.
The same lock serializes OAuth state creation/consumption with unlink, which removes every pending state before it reports success.
Callback state deletion commits before token exchange while the session-level actor lock remains held, so a failed callback cannot redeem the same one-time state again.
Pool acquisition, statements, transactions, and advisory-lock waits are bounded; idle pool failures initiate metadata-only controlled shutdown.

The service uses `@github/copilot-sdk@1.0.16` with `mode: "empty"`, `useLoggedInUser: false`, actor-isolated storage, exact `hydrafusion`, no fallback, no session store, no config discovery, no skills, extensions, canvases, built-in tools, or custom tools.
It supplies only an actor-owned token provider and the accepted issue #344 MCP contract.
Exact-model session creation with that provider is the per-actor entitlement check; client-global unauthenticated model listing is not used.
A bounded, immediately closed exact-model session lets authenticated status checks establish readiness before the browser submits its first question.
Readiness probes and chats share the same atomic global and per-actor admission limits; a full status probe returns `429 rate_limit` and releases its reservation after teardown.
The MCP server is a local stdio child with a minimal explicit environment, a mounted finance database URL file, and allowlisted read-only tools.
Startup probes the production MCP child with `connect`, `listTools`, and `close`; missing or extra registrations and missing output schemas disable production.

The HTTP stream implements the issue #343/#349 Ask Penge `1.0` event contract.
Events are zod-validated, ordered, session-bound, and terminal after completion or error.
Prompt and transcript content are process-memory-only and removed when a bounded request ends.
Audit storage contains only pseudonymous actor/session IDs, tool name, status, duration, and argument key names.

OAuth/audit tables use a dedicated schema-only Alembic chain and database.
Deployment owns database/role lifecycle and grants; the finance migration graph remains untouched.
Postgres dependency `pg` is required for parameterized OAuth/audit persistence and startup privilege inspection.
`pino` is required by the repository logging policy for structured redacted service logs.
The official Copilot and MCP SDK dependencies are required to execute and verify their respective runtime protocols instead of maintaining incompatible local implementations.

## Consequences

### Positive

- Cross-user credentials, sessions, and quotas are isolated.
- Raw finance tables, arbitrary SQL, network MCP, and ambient agent tools remain unavailable.
- OAuth credentials can be rotated without invalidating envelopes encrypted by retained keys.
- Disconnects and all terminal paths clean up SDK and MCP processes without transcript persistence.

### Negative

- Chat remains unavailable to an actor until exact `hydrafusion` session creation succeeds with that actor's linked token.
- Production requires coordinated reverse-proxy headers and mounted secrets from issue #342.
- The accepted issue #344 MCP branch must land before the production readiness probe can pass.

### Neutral

- Deployment creates the service role and supplies authentication using the versioned Postgres secret mechanism.

## Links

- Parent issue #341
- Architecture issue #345 and ADR-0053
- MCP source coverage issue #344
- Web stream contract issue #343 and PR #349
- Infrastructure issue #342
- [Chat runtime operations](../runbook/chat-runtime.md)
