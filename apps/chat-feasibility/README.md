# @penge/chat-feasibility

Bounded, synthetic Copilot SDK architecture proof for issue #345.
This package is not a production service and makes no live model call.
Issue #346 replaces it with `apps/chat`.

The package pins `@github/copilot-sdk@1.0.16` and type-checks the exact
empty-mode, user-scoped token, streaming, local stdio MCP, and tool-filter
configuration that the production backend must preserve.
Its `issue-344-v1` contract pins the final MCP registration set from #344:
`_meta` plus 16 chat tools. The chat allowlist exposes only those 16 tools;
the MCP-only `_meta` capability is registered for protocol discovery but is
never available to the model.
