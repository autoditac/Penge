# @penge/chat-feasibility

Bounded, synthetic Copilot SDK architecture proof for issue #345.
This package is not a production service and makes no live model call.
Issue #346 replaces it with `apps/chat`.

The package pins `@github/copilot-sdk@1.0.16` and type-checks the exact
empty-mode, user-scoped token, streaming, local stdio MCP, and tool-filter
configuration that the production backend must preserve.
The isolated entitlement diagnostic requires your own explicit
`PENGE_CHAT_DIAGNOSTIC_GITHUB_TOKEN`; persisted login is not an authentication
source for it.
See the [chat runbook](../../docs/runbook/chat.md) for safe credential injection.
MCP configuration accepts exactly one direct/file database credential source
and binds canonical actor/session ULID audit pseudonyms to the trusted caller.
After #350, repository source defines `_meta` plus 16 implemented chat tools.
The harness proves that the SDK configuration targets those 16, excluding `_meta`; it does
not start the MCP child, call `tools/list`, or invoke a tool.
Separately, `just mcp-test` exercises stdio discovery and a synthetic
`query_net_worth` call using the server registry and an in-memory query fixture.
It does not start the production entrypoint or a Copilot session.
The landed `issue-344-v1` registration contract is independently checked by
the stdio `tools/list` test against the exact 17-name set.
Registration does not authorize exposing transaction search or detail to a
model: those proposed tools conflict with ADR-0005's aggregate-only boundary.
Production also remains blocked until the policy conflict is resolved as
described in ADR-0053 and the selected contract is independently verified.

The SDK base directory is derived from the validated actor ID below a trusted
absolute root.
The runtime receives a small allowlisted environment, and the MCP child
receives only its explicit data-access configuration; ambient GitHub/Copilot
credentials are never inherited.
