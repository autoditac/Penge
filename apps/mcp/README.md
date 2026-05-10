# @penge/mcp

Skeleton Model Context Protocol server. Read-only gateway between LLM hosts
(Claude Desktop, VS Code Copilot Chat, etc.) and the Penge data platform.

This package only ships the server loop, the tool registry, the audit-log
redactor and a `_meta` health-check tool. The real query tools land in
follow-up issues (#45, #46, #47, #49). See
[`docs/decisions/0023-mcp-server-architecture.md`](../../docs/decisions/0023-mcp-server-architecture.md)
for the architectural decision and
[`docs/decisions/0005-llm-access-via-mcp-only.md`](../../docs/decisions/0005-llm-access-via-mcp-only.md)
for the policy.

## Run locally

```bash
pnpm install
just mcp-dev
```

`mcp-dev` runs `tsx watch src/index.ts` over stdio. Connect from Claude Desktop
by adding the snippet from ADR-0023 to `claude_desktop_config.json`.

## Environment

| Variable            | Required | Description                                                                    |
| ------------------- | -------- | ------------------------------------------------------------------------------ |
| `PENGE_DB_URL`      | yes      | Postgres connection URL. The server forces `default_transaction_read_only=on`. |
| `PENGE_DUCKDB_PATH` | yes      | Path to the analytics DuckDB file. Opened read-only.                           |
| `PENGE_MCP_LOG_DIR` | no       | Audit log directory. Defaults to `logs/mcp/`.                                  |

## Audit log

Every tool invocation is logged to `logs/mcp/audit-YYYY-MM-DD.jsonl` and
mirrored to stderr. Argument values for fields whose name matches
`account|iban|cpr|tax_id|name|email` (case-insensitive) are replaced with
`"[REDACTED]"` before the record is written. See `src/audit.ts`.
