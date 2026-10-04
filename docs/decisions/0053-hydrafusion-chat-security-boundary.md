# 0053 — Secure HydraFusion chat service boundary

- **Status:** Accepted
- **Date:** 2026-10-04
- **Deciders:** @autoditac
- **Tags:** mcp, security, web, infra, chat

## Context and Problem Statement

Issue #345 is the architecture and feasibility gate for the private Ask Penge
feature in parent issue #341.
Penge needs an explanation-first chat service without weakening ADR-0005's
MCP-only data boundary or ADR-0023's process-local stdio transport.

The service eventually implemented by issue #346 must support two household
members.
Each Penge actor links and uses that person's own GitHub account, Copilot
entitlement, OAuth credentials, quota, and session.
The service must never share one household account or credential between actors.
Copilot entitlement belongs to the linked GitHub identity; this decision does
not incorrectly require one person to have different GitHub and Copilot login
names.

## Decision Drivers

- Raw finance rows, statements, credentials, and arbitrary SQL must remain
  unavailable to the model.
- Every SDK session must have one pseudonymous Penge actor and one matching
  user-scoped token provider.
- The exact `hydrafusion` model must be available to that linked user.
  There is no model fallback.
- Runtime defaults, shell, filesystem, web fetch, skills, extensions, and
  custom tools must be absent.
- MCP remains a child process over stdio and must not gain HTTP or SSE
  transport.
- Tests must use synthetic identities, tokens, events, and finance arguments.

## Considered Options

1. **Loopback chat service using empty-mode Copilot SDK sessions and local Penge
   MCP** — chosen.
2. **Shared household Copilot identity or ambient logged-in runtime identity** —
   rejected.
3. **HTTP/SSE MCP or direct database access from the chat service** — rejected.
4. **Fallback model when HydraFusion is unavailable** — rejected.

## Decision

Issue #346 will own a loopback-only `apps/chat` service.
The WebUI may call that service through the authenticated reverse proxy, but no
MCP, Copilot runtime, database, or raw tool endpoint is exposed.
The chat service spawns `@penge/mcp` as a local stdio child and selects tools by
an explicit, versioned contract.

Every production SDK client and session must preserve the executable contract
in `apps/chat-feasibility`:

- `CopilotClient` uses `mode: "empty"`, an actor-isolated `baseDirectory`,
  `useLoggedInUser: false`, and error-only SDK logging.
- The session sets `model` and `allowedModels` to exactly `hydrafusion`, enables
  streaming, disables session-store/config discovery, and includes no built-in
  skills, canvases, or extensions.
- A session-scoped `gitHubTokenProvider` is owned by the same pseudonymous actor
  as the request.
  Ambient machine credentials are never used in production.
- `availableTools` contains only source-qualified
  `mcp:penge-<tool-name>` entries.
  `excludedTools` denies every `builtin:*` and `custom:*` source, and every
  permission request is rejected.
- The only MCP server configuration has `type: "stdio"` and a bounded `tools`
  array.
  An HTTP/SSE URL is structurally absent.
- MCP OAuth token storage is in memory.
  Chat transcript content is not retained after the bounded session lifetime.
  Audits contain only pseudonymous actor/session identifiers, tool/status/
  duration, and redacted arguments.
- SDK storage is derived as `<trusted absolute root>/<validated actor ID>`;
  callers cannot supply a reusable actor directory.
- The SDK runtime receives an allowlisted child environment without ambient
  GitHub/Copilot authentication variables.
  The MCP child receives only its explicit read-only data configuration.

`PENGE_CHAT_MODEL=hydrafusion` is mandatory.
`PENGE_CHAT_FALLBACK_MODEL` must be unset.
`PENGE_CHAT_ENABLE_PRODUCTION=1` is only a process-wide deployment switch and
does not grant model access to any actor.
There is deliberately no process-wide entitlement flag.
Issue #346 must persist a successful `listModels()` verification keyed by the
tuple `(actor ID, normalized linked GitHub login, exact model ID)` and pass that
actor-scoped record into session configuration.
The runtime rejects a record belonging to another actor or linked identity.
Verification is never inferred from documentation, another user, or the
deployment switch.

### Dependency ownership and pin

The proof package pins `@github/copilot-sdk@1.0.16` exactly.
On 2026-10-04, `1.0.16` was the current npm release and declared Node
`^20.19.0 || >=22.12.0`.
Its published types are the evidence for empty-mode storage, required
`availableTools`, `ToolSet` source-qualified filters, session-scoped token
providers, streaming events, model listing, and local stdio MCP configuration.
An exact pin prevents SDK/runtime behavior from drifting during review.

`@penge/mcp` intentionally does not depend on the Copilot SDK.
The temporary `@penge/chat-feasibility` package owns the pin for #345, and
issue #346 must move the same reviewed pin into production `apps/chat` when it
replaces the proof package.

### Tool-contract seam

`issue-344-v1` is the accepted target MCP contract from #344.
Its registration set is `_meta` plus 16 chat tools covering the
existing eight capabilities, source coverage, bounded transaction
search/detail, household taxonomy/rule/merchant summaries, and
merchant-reference status/search.
The model-facing allowlist contains only the 16 chat tools; `_meta` remains
registered for MCP protocol discovery and is never exposed to the model.
At this PR's current base, the real server registers `_meta` plus only the
eight existing tools.
The harness therefore configures only those eight and raises
`chat/mcp_contract_unavailable` when that observed set is checked against
`issue-344-v1`.
Production cannot claim or enable the target contract until #350 is merged and
an independent stdio `tools/list` integration test proves all 17 names.
Issue #346 must reject unknown versions rather than silently widening the tool
set.

### Feasibility and entitlement evidence

The synthetic harness type-checks the actual `1.0.16` client/session objects,
local stdio server config, `ToolSet` filters, user-token ownership guard,
official stream event names, and typed unavailable-model error.
It makes no model call and is not live acceptance.

The token-safe check on 2026-10-04 called only `listModels()` for the currently
authenticated user, logged at error level, and emitted only the exact-ID result:

```json
{ "exactModel": "hydrafusion", "entitled": false, "matchCount": 0 }
```

No token, identity, prompt, or finance data was printed or persisted.
Therefore real entitlement is unproven, the production feature remains
disabled, and no other model may substitute.

## Consequences

### Positive

- The existing MCP privacy boundary remains intact.
- Actor/token isolation and deny-by-default tools are executable contracts.
- Downstream work has versioned seams instead of inferred tool names.
- Missing HydraFusion entitlement fails explicitly.

### Negative

- Live chat cannot ship until each authorized user independently passes the
  exact model check.
- Live chat cannot ship until the real stdio server's `tools/list` response
  proves `issue-344-v1`.
- Changes to the accepted #344 tool set require a new explicit contract
  version; registration alone never grants model access.
- Per-user OAuth, cancellation, cleanup, and retention enforcement remain
  implementation work for #346.

### Neutral

- Deterministic reports remain the product truth; chat only explains bounded
  tool evidence.

## Downstream Contracts

| PBI  | Contract provided by this decision                                                                                                                                                                                                                        |
| ---- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| #344 | Implement `issue-344-v1`: register `_meta` plus 16 chat tools, expose only the 16 chat tools to the model, and preserve declared schemas, bounds, evidence metadata, freshness, EUR/DKK behavior, and audit fields.                                      |
| #346 | Own `apps/chat` and the SDK pin; preserve empty mode, actor/linked-identity-scoped entitlement and token providers, exact model/no fallback, deny-by-default tools, stdio-only MCP, ephemeral transcript, typed stream/errors, cancellation, and cleanup. |
| #343 | Consume a versioned stream contract; render buffered answer deltas and sanitized tool/evidence states, never raw arguments/JSON or chain-of-thought; expose explicit unavailable-model/auth/cancel/error states.                                          |
| #342 | Keep chat loopback-only behind trusted identity headers; expose no MCP/runtime port; mount encryption keys as secrets; add quota-free health, redacted observability, cleanup, rollback, and two-user acceptance after entitlement exists.                |

## Links

- [ADR-0005](0005-llm-access-via-mcp-only.md)
- [ADR-0023](0023-mcp-server-architecture.md)
- [Ask Penge product brief](../web/ask-penge-product-brief.md)
- [Chat safety runbook](../runbook/chat.md)
- [Copilot SDK Node.js package documentation](https://github.com/github/copilot-sdk/tree/main/nodejs)
- [Copilot SDK getting started and streaming documentation](https://github.com/github/copilot-sdk/blob/main/docs/getting-started.md)
