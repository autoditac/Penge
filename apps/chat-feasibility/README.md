# @penge/chat-feasibility

Bounded, synthetic Copilot SDK architecture proof for issue #345.
This package is not a production service and makes no live model call.
Issue #346 replaces it with `apps/chat`.

The package pins `@github/copilot-sdk@1.0.16` and type-checks the exact
empty-mode, user-scoped token, streaming, local stdio MCP, and tool-filter
configuration that the production backend must preserve.
Repository source defines `_meta` plus eight implemented chat tools.
The harness proves that the SDK configuration targets only those eight; it does
not start the MCP child, call `tools/list`, or invoke a tool.
The planned `issue-344-v1` contract is `_meta` plus 16 chat tools, but #350 is
not merged; production readiness must remain blocked until an independent
stdio `tools/list` result proves that exact registration set.

The SDK base directory is derived from the validated actor ID below a trusted
absolute root.
The runtime receives a small allowlisted environment, and the MCP child
receives only its explicit data-access configuration; ambient GitHub/Copilot
credentials are never inherited.
