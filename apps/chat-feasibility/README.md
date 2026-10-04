# @penge/chat-feasibility

Bounded, synthetic Copilot SDK architecture proof for issue #345.
This package is not a production service and makes no live model call.
Issue #346 replaces it with `apps/chat`.

The package pins `@github/copilot-sdk@1.0.16` and type-checks the exact
empty-mode, user-scoped token, streaming, local stdio MCP, and tool-filter
configuration that the production backend must preserve.
Its provisional `issue-345-v1-provisional` tool contract contains only tools
that exist today.
Issue #344 must publish a new version after its source-coverage tool names and
schemas are final; no code may interpret this baseline as complete source
coverage.
