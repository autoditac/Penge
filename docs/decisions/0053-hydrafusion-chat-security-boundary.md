# 0053 — Secure Copilot Fusion chat service boundary

- **Status:** Accepted
- **Date:** 2026-10-04
- **Deciders:** @autoditac
- **Tags:** mcp, security, web, infra, chat

## Context and Problem Statement

Issue #345 is the architecture and feasibility gate for the private Ask Penge
feature in parent issue #341.
Penge needs an explanation-first chat service without weakening ADR-0005's
MCP-only data boundary or ADR-0023's process-local stdio transport.
ADR-0005's default model boundary is aggregate tool outputs, not raw
transactions.
The #344 contract includes transaction search and detail tools; a proposed
ADR-0005 amendment (#390) would narrowly permit those two bounded outputs for
actor-authenticated `hydrafusion` sessions, but it is not yet owner-accepted.
This decision grants no exception to ADR-0005.

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

1. **Host-private chat service using empty-mode Copilot SDK sessions and local
   Penge MCP** — chosen.
2. **Shared household Copilot identity or ambient logged-in runtime identity** —
   rejected.
3. **HTTP/SSE MCP or direct database access from the chat service** — rejected.
4. **Fallback model when Copilot Fusion is unavailable** — rejected.

## Decision

Issue #346 will own an `apps/chat` service reachable only over a host-private
transport: TCP loopback (`127.0.0.1`/`::1`) for development, or — proposed, not
implemented by this ADR's feasibility layer — an owner-permissioned Unix domain
socket in a dedicated directory for deployment.
Deployment must not publish a container port or use host networking; the
transport choice does not relax trusted-identity-header or proxy-secret checks.
The Unix socket variant, including its permissions and negative network tests,
is owned by #347 together with ADR-0054/ADR-0055 and requires owner acceptance.
The WebUI may call that service through the authenticated reverse proxy, but no
MCP, Copilot runtime, database, or raw tool endpoint is exposed.
The chat service spawns `@penge/mcp` as a local stdio child and selects tools by
an explicit, versioned contract.

Every production SDK client and session must preserve the executable contract
in `apps/chat-feasibility`:

- `CopilotClient` uses an explicit stdio connection, `mode: "empty"`, an
  actor-isolated `baseDirectory`, `useLoggedInUser: false`, and error-only SDK
  logging; an ambient SDK transport override cannot select in-process hosting.
- The session sets `model` and `allowedModels` to exactly `hydrafusion`, enables
  streaming, disables session-store/config discovery, and includes no built-in
  skills, canvases, or extensions.
- A session-scoped `gitHubTokenProvider` is owned by the same pseudonymous actor
  as the request.
  Ambient machine credentials are never used in production.
- `availableTools` contains only source-qualified
  `mcp:penge-<tool-name>` entries.
  `excludedTools` denies every `builtin:*` and `custom:*` source, and every
  non-MCP permission request is rejected.
  A read-only request for the exact `penge` server and configured tool
  allowlist is approved for that call once; it is never remembered for the
  session.
- The only MCP server configuration has `type: "stdio"` and a bounded `tools`
  array.
  An HTTP/SSE URL is structurally absent.
  Exactly one database credential source (`PENGE_DB_URL` or
  `PENGE_DB_URL_FILE`) is accepted; MCP validates and reads file secrets.
  Trusted `actor_<ULID>` and `session_<ULID>` pseudonyms bind child audit
  attribution to the current actor and SDK session.
  Conflicting child attribution is rejected rather than overwritten silently.
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
Issue #346 must persist a successful actor-scoped model availability verification
keyed by the tuple `(actor ID, normalized linked GitHub login, exact model ID)`
and pass that actor-scoped record into session configuration.
The response must contain exactly one matching model; if policy metadata is
present, its state must be `enabled`.
Client-wide `listModels()` does not establish entitlement for a separately
authenticated session actor.
The SDK's experimental session-scoped model list requires validated response
semantics; session creation alone does not prove model execution.
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

`issue-344-v1` is the landed MCP registration contract from #344/#350.
Its registration set is `_meta` plus 16 tools covering the
existing eight capabilities, source coverage, bounded transaction
search/detail, household taxonomy/rule/merchant summaries, and
merchant-reference status/search.
The proposed model-facing allowlist contains those 16 tools; `_meta` remains
registered for MCP protocol discovery and is never exposed to the model.
In particular, `search_household_transactions` and
`get_household_transaction_detail` exceed ADR-0005's aggregate-only default.
The proposed ADR-0005 amendment from #390 would permit only those two bounded
tools; merging that proposal is not owner acceptance.
They must not be exposed to a live model until the owner accepts that
amendment through repository review, or until they are removed from the
model-facing allowlist in an updated contract verified to satisfy the
aggregate-only boundary.
After integration of #350, repository source defines all 17 registered tools.
The synthetic harness configures the 16 model tools, excluding `_meta`, but does not start the MCP child,
inspect `tools/list`, or invoke a tool.
It raises `chat/mcp_contract_unavailable` for missing, duplicate, or unexpected
registered names.
An independent stdio `tools/list` integration test proves all 17 names using
the shared production tool factory, and invokes `query_net_worth` synthetically.
Registration evidence alone does not authorize model exposure or resolve the
privacy gate.
Issue #346 must reject unknown versions rather than silently widening the tool
set, and must verify the selected policy-compliant contract before enabling it.

### Feasibility and entitlement evidence

The synthetic harness type-checks the actual `1.0.16` client/session objects,
local stdio server configuration, `ToolSet` filters, user-token ownership
guard, official stream event names, and typed unavailable-model error.
It does not spawn MCP, perform `tools/list`, invoke a tool, or make a model
call, and is not live acceptance.
The separate MCP stdio contract test spawns a synthetic server using the
production registry and a fake query runner, checks the read-only tool list,
and invokes `query_net_worth` with synthetic input.
It does not start the production entrypoint or establish a Copilot session.
The separate entitlement probe has a bounded deadline and attempts graceful,
then forced, SDK shutdown.
It retains isolated temporary storage instead of deleting it when termination
cannot be confirmed.
It requires the operator's own explicit `PENGE_CHAT_DIAGNOSTIC_GITHUB_TOKEN`,
sets client `gitHubToken` and `useLoggedInUser: false`, and sanitizes the runtime
environment.
An isolated empty-mode client cannot rely on persisted Copilot/keychain login.
There is no ambient or shared-account credential fallback.

The historical check on 2026-10-04 called only `listModels()`, logged at error
level, and emitted only the exact-ID result:

```json
{ "exactModel": "hydrafusion", "entitled": false, "matchCount": 0 }
```

The historical check used implicit authentication and did not verify which
account supplied the result.
It is not current actor-specific entitlement evidence.
No token, identity, prompt, or finance data was printed.
Real entitlement remains unproven, the production feature remains
disabled, and no other model may substitute.

## Consequences

### Positive

- MCP remains the intended data ingress; the transaction-level tools depend on
  owner acceptance of the proposed ADR-0005 amendment.
- Actor/token isolation and deny-by-default tools are executable contracts.
- Downstream work has versioned seams instead of inferred tool names.
- Missing Copilot Fusion entitlement fails explicitly.

### Negative

- Live chat cannot ship until each authorized user independently passes the
  exact model check.
- Live chat cannot ship until the proposed ADR-0005 amendment is
  owner-accepted or the transaction tools are removed, as described above, and the real stdio server's `tools/list` response proves the selected
  contract.
- Changes to the #344 tool set require a new explicit contract
  version; registration alone never grants model access.
- Per-user OAuth, cancellation, cleanup, and retention enforcement remain
  implementation work for #346.

### Neutral

- Deterministic reports remain the product truth; chat only explains bounded
  tool evidence.

## Downstream Contracts

| PBI  | Contract provided by this decision                                                                                                                                                                                                                        |
| ---- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| #344 | Landed in #350: `issue-344-v1` registration of `_meta` plus 16 tools, preserving schemas, bounds, evidence metadata, freshness, EUR/DKK behavior, and audit fields; model exposure still requires owner acceptance of the proposed ADR-0005 amendment. |
| #346 | Own `apps/chat` and the SDK pin; keep production disabled until the proposed ADR-0005 amendment is owner-accepted or the transaction tools are removed, and preserve empty mode, actor/linked-identity-scoped entitlement and tokens, exact model/no fallback, deny-by-default tools, stdio-only MCP, ephemeral transcript, typed stream/errors, cancellation, and cleanup. |
| #343 | Consume a versioned stream contract; render buffered answer deltas and sanitized tool/evidence states, never raw arguments/JSON or chain-of-thought; expose explicit unavailable-model/auth/cancel/error states.                                          |
| #342 | Keep chat on a host-private transport behind trusted identity headers; expose no MCP/runtime port; mount encryption keys as secrets; add quota-free health, redacted observability, cleanup, rollback, and two-user acceptance after entitlement exists.  |

## Links

- [ADR-0005](0005-llm-access-via-mcp-only.md)
- [ADR-0023](0023-mcp-server-architecture.md)
- [Ask Penge product brief](../web/ask-penge-product-brief.md)
- [Chat safety runbook](../runbook/chat.md)
- [Copilot SDK Node.js package documentation](https://github.com/github/copilot-sdk/tree/main/nodejs)
- [Copilot SDK getting started and streaming documentation](https://github.com/github/copilot-sdk/blob/main/docs/getting-started.md)
