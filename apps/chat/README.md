# Penge Chat

This package provides the isolated multi-user chat backend for Penge.

It is intentionally restricted to:

- loopback-only HTTP listeners
- local stdio MCP invocation only
- a strict allowlist of read-only Penge tools
- exact HydraFusion `mode: "empty"` runtime with no fallback
- encrypted token storage, versioned OAuth state, and pseudonymous audit metadata

The runtime does not persist transcripts and it never opens the estimate service to finance tables outside the OAuth link tables.
