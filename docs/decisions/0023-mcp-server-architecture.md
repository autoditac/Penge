# 0023 — MCP server architecture (TypeScript skeleton)

- **Status:** Accepted
- **Date:** 2026-05-10
- **Deciders:** @autoditac
- **Tags:** mcp, security, vault

## Context and Problem Statement

ADR-0005 fixed the policy: every LLM in the Penge system reaches data
exclusively through a Model Context Protocol (MCP) server with typed tools.
This ADR records the *implementation* shape — language, layout, transport,
auth surface, audit logging — that the first set of tools (issues `#45`,
`#46`, `#47`, `#49`) and every future tool plug into.

We need a skeleton that:

1. Boots locally with `just mcp-dev` and is reachable from Claude Desktop.
2. Connects read-only to Postgres (operational tables) and DuckDB (mart
   tables produced by dbt — see ADR-0001).
3. Logs every tool call with redacted arguments so the audit trail is real
   from day one, before any tool ships.
4. Is type-safe end-to-end and refuses to start with a misconfigured env.

## Decision Drivers

- **Provider neutrality** — must work with any MCP host (Claude Desktop, VS
  Code Copilot Chat, custom tools).
- **Read-only by construction** — even a buggy tool implementation must not
  be able to mutate the operational database.
- **Audit-first** — the audit log is part of the trust story, not an add-on.
- **Boring TypeScript** — a single small Node service, no extra runtime
  (no Bun, no Deno) so deployment matches the rest of the stack.
- **Strict typing** — `tsc --strict`, `noUncheckedIndexedAccess`,
  `exactOptionalPropertyTypes`, zod-validated runtime inputs.

## Considered Options

1. **TypeScript + `@modelcontextprotocol/sdk` over stdio** (chosen).
2. **Python MCP server** sharing the existing `uv` workspace.
3. **Single-binary Go MCP server.**

## Decision

We chose **Option 1**: a TypeScript package at `apps/mcp/`, using the
official `@modelcontextprotocol/sdk`, communicating over stdio.

### Layout

```text
apps/mcp/
  src/
    audit.ts        # JSONL audit log + key-based redactor
    config.ts       # zod-validated env loader (PENGE_DB_URL, ...)
    db.ts           # pg.Pool (read-only) + DuckDB path holder
    registry.ts     # ToolRegistry, ToolDefinition<I, O>
    server.ts       # buildServer(): wires registry → MCP handlers
    tools/
      meta.ts       # `_meta` health-check tool
    index.ts        # stdio entrypoint, signal handling
  tests/            # vitest: audit redaction, server startup, _meta call
  eslint.config.js  # typescript-eslint flat config
  tsconfig.json     # strict; ES2022 + NodeNext modules
  vitest.config.ts
  package.json
```

### Key choices

- **Transport:** stdio. MCP hosts spawn the binary directly; no network
  ports, no auth surface. Future remote scenarios can layer SSE on top
  without changing tool code.
- **Read-only enforcement:** the Postgres pool installs a
  `SET default_transaction_read_only = on` hook on every checked-out
  connection; DuckDB is opened with the read-only flag by tool authors.
- **Tool definition shape:** every tool is a `ToolDefinition<I, O>` with a
  zod input schema, a zod output schema, a description, and a handler.
  `server.ts` derives the JSON Schema sent to the host via
  `zod-to-json-schema`. Tools never see raw JSON-RPC.
- **Audit log:** `logs/mcp/audit-YYYY-MM-DD.jsonl`, mirrored to stderr.
  Every record carries `ts`, `tool`, redacted `args`, `status`, `durationMs`,
  optional `error`. Argument values for fields whose name matches
  `account|iban|cpr|tax_id|name|email` (case-insensitive) are replaced with
  `"[REDACTED]"` *before* the record is written. The redactor is recursive
  (objects and arrays).
- **Built-in `_meta` tool:** returns server name, version, and the list of
  registered tools. Lets the loop be tested before any real tool exists,
  and gives MCP hosts a stable health probe.

### Claude Desktop snippet

`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or
`%APPDATA%/Claude/claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "penge": {
      "command": "pnpm",
      "args": ["--filter", "@penge/mcp", "start"],
      "cwd": "/absolute/path/to/Penge",
      "env": {
        "PENGE_DB_URL": "postgres://penge:penge@localhost:5432/penge",
        "PENGE_DUCKDB_PATH": "/absolute/path/to/Penge/data/marts.duckdb"
      }
    }
  }
}
```

For local development, run `just mcp-build` once and switch `args` to
`["--filter", "@penge/mcp", "exec", "node", "dist/index.js"]` (or use the
`penge-mcp` bin) — `tsx watch` is for fast inner-loop work, not for hosts.

## Consequences

### Positive

- Provider-neutral (works with any MCP host).
- Audit log exists *before* any tool, so every future tool inherits it.
- Strict TypeScript catches schema/handler drift at compile time.
- No new ports, no new auth code paths.

### Negative

- A second runtime (Node) sits next to the Python stack. Mitigated: pnpm
  workspace is small, deployments share the same compose file.
- Stdio transport ties the server lifecycle to its host. We accept that —
  remote MCP is out of scope for the home setup.

### Neutral

- DuckDB connections are created lazily by tools, not by the skeleton, to
  keep the cold-start cheap and unit-testable.

## Alternatives in detail

### Python MCP server

Tempting because it shares the `uv` workspace. Rejected: the official
TypeScript SDK is more mature, MCP hosts publish TS examples first, and
strict zod validation is cleaner than runtime pydantic validation for the
JSON-RPC frontier. The numerical engine stays in Python; MCP tools shell
out via internal RPC if needed.

### Single-binary Go server

Best deploy story, worst SDK story today. Rejected for now; revisit if the
TS SDK becomes a maintenance burden.

## Links

- ADR-0001 (Self-hosted Postgres + DuckDB stack)
- ADR-0005 (LLM access via MCP only)
- `apps/mcp/README.md`
- Issue #44 (this skeleton); follow-ups: #45, #46, #47, #49
