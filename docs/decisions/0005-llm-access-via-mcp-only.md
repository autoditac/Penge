# 0005 — LLM access exclusively via MCP server with typed tools

- **Status:** Proposed
- **Date:** 2026-05-06
- **Amendment date:** 2026-11-19
- **Deciders:** @autoditac
- **Tags:** mcp, security, sim

## Context and Problem Statement

We want to ask natural-language questions about finances ("what was my
average monthly net savings rate over the last 12 months in EUR?",
"project my FIRE date if I increase contributions by 500 EUR/month") and
get numerically correct answers. The model must not receive account credentials
or raw source payloads, and financial evidence must remain bounded and
reproducible through typed tools.

The isolated multi-user chat use case needs record-level evidence for reviewed
questions. This decision therefore defines a narrow exception to the
aggregate-only output boundary for two read-only MCP tools.

## Decision Drivers

- Determinism: numeric answers must come from code we control, not from
  the LLM’s own arithmetic.
- Privacy: constrain transaction-level disclosure to two named, bounded MCP
  tools in actor-authenticated Copilot Fusion sessions; never expose credentials,
  raw source payloads, or arbitrary query access.
- Provider neutrality: usable from Claude Desktop, VS Code, or any other
  MCP host.
- Testability: LLM behavior must be evaluable against a golden-question
  suite.

## Considered Options

1. **MCP server with typed tools** — TypeScript MCP server exposes a fixed set of typed tools (`query_net_worth`, `query_cashflow`, `run_scenario`, `search_documents`, `compute_tax_year`, `search_household_transactions`, `get_household_transaction_detail`). The model only sees tool inputs and schema-validated outputs.
2. **Direct SQL access** — give the LLM read-only Postgres credentials and let it write SQL.
3. **Custom REST API + prompt-engineered LLM** — bespoke HTTP API consumed by a prompt template per provider.
4. **RAG over a Parquet dump** — vector-search over a flattened export, LLM aggregates.

## Decision

We chose **Option 1: MCP-only**.

The MCP server is the single LLM ingress. Each tool has a typed JSON Schema
input and a deterministic output. Numbers come from the same Python packages
used by the dashboard (ADR-0002). A 20-question golden-eval suite gates
releases.

The default for financial questions remains aggregate-only. As a narrow
exception, an actor-authenticated Copilot Fusion session using the exact
`hydrafusion` model may invoke `search_household_transactions` and
`get_household_transaction_detail` through the read-only local MCP server.
The search tool returns a bounded page over a bounded date range; the detail
tool returns one stable-ID transaction with schema-bounded allocations,
classification, audit references, and linked PayPal enrichment. Both tools
bound and redact free-text fields according to their MCP output schemas.

This exception does not authorize account credentials, raw source files or
payloads, arbitrary SQL, unbounded exports, other transaction-level tools, or
transaction-level output to an unscoped model session. The allowed outputs
still contain sensitive financial details; this decision records that privacy
tradeoff but does not establish live actor entitlement, two-user isolation, or
production readiness. Those remain separate gates in
[ADR-0055](0055-isolated-multi-user-chat-runtime.md).

## Consequences

### Positive

- Numeric correctness is enforced by code, not by prompt.
- Same answer regardless of LLM provider.
- Credentials and raw source payloads remain inaccessible to the model;
  transaction-level fields are limited to the two named bounded MCP outputs.
- Eval suite makes regressions visible.

### Negative

- Every new question class needs a new tool or tool extension.
- Initial cost to design typed tool schemas.
- Transaction-level output can reveal sensitive purchase details, so the two
  tools remain limited to actor-authenticated `hydrafusion` sessions and
  require the separate production acceptance gates in ADR-0055.

### Neutral

- Document semantic search (`search_documents`) still returns text snippets,
  so document-level privacy depends on what is stored in the vault.

## Alternatives in detail

### Direct SQL access

Rejected: LLMs hallucinate joins; SQL execution rights to a Postgres with
PII is a security regression.

### REST API + prompt engineering

Rejected: per-provider prompts diverge, drift from MCP ecosystem.

### RAG-only

Rejected: vector search cannot reliably answer numeric/tax questions.

## Links

- ADR-0002 (monorepo)
- `apps/mcp/src/tools/searchHouseholdTransactions.ts`
- `apps/mcp/src/tools/getHouseholdTransactionDetail.ts`
- [ADR-0055 — Isolated multi-user chat runtime](0055-isolated-multi-user-chat-runtime.md)
- Issues #44–#49, #54
