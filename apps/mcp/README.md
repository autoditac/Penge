# @penge/mcp

Model Context Protocol server. Read-only gateway between LLM hosts
(Claude Desktop, VS Code Copilot Chat, etc.) and the Penge data platform.

This package ships the server loop, the tool registry, the audit-log
redactor, and the read-only tool surface for net worth, cashflow, tax,
scenario, document-search, and household-planning questions. See
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

| Variable               | Required | Description                                                                    |
| ---------------------- | -------- | ------------------------------------------------------------------------------ |
| `PENGE_DB_URL`         | yes      | Postgres connection URL. The server forces `default_transaction_read_only=on`. |
| `PENGE_DUCKDB_PATH`    | yes      | Path to the analytics DuckDB file. Opened read-only.                           |
| `PENGE_MCP_LOG_DIR`    | no       | Audit log directory. Defaults to `logs/mcp/`.                                  |
| `PENGE_MCP_ACTOR_ID`   | no       | Opaque pseudonymous actor ID; 8–64 alphanumeric/`_`/`-` characters.            |
| `PENGE_MCP_SESSION_ID` | no       | Opaque bounded-lifetime session ID with the same format.                       |

## Audit log

Every tool invocation is logged to `logs/mcp/audit-YYYY-MM-DD.jsonl` and
mirrored to stderr. Argument values for fields whose name matches
`account|iban|cpr|tax_id|name|email|query|prompt|transcript|payload|secret|token|message|content`
(case-insensitive) are replaced with `"[REDACTED]"` before the record is
written.
Audit attribution is pseudonymous and process-scoped; names, email addresses,
prompts, transcripts, OAuth credentials, and tool result payloads are not audit
fields.
See `src/audit.ts` and the
[source coverage contract](../../docs/mcp/source-coverage.md).
