# 0005 — LLM access exclusively via MCP server with typed tools

- **Status:** Accepted
- **Date:** 2026-05-06
- **Deciders:** @autoditac
- **Tags:** mcp, security, sim

## Context and Problem Statement

We want to ask natural-language questions about finances ("what was my
average monthly net savings rate over the last 12 months in EUR?",
"project my FIRE date if I increase contributions by 500 EUR/month") and
get numerically correct answers. The LLM must not see raw transactions or
account credentials, must produce reproducible numbers, and must be
swappable across providers (Claude, GPT, local models).

## Decision Drivers

- Determinism: numeric answers must come from code we control, not from
  the LLM’s own arithmetic.
- Privacy: raw transaction-level data must not leave our infrastructure.
- Provider neutrality: usable from Claude Desktop, VS Code, or any other
  MCP host.
- Testability: LLM behavior must be evaluable against a golden-question
  suite.

## Considered Options

1. **MCP server with typed tools** — TypeScript MCP server exposes a fixed set of typed tools (`query_net_worth`, `query_cashflow`, `run_scenario`, `search_documents`, `compute_tax_year`). The LLM only ever sees tool inputs/outputs.
2. **Direct SQL access** — give the LLM read-only Postgres credentials and let it write SQL.
3. **Custom REST API + prompt-engineered LLM** — bespoke HTTP API consumed by a prompt template per provider.
4. **RAG over a Parquet dump** — vector-search over a flattened export, LLM aggregates.

## Decision

We chose **Option 1: MCP-only**.

The MCP server is the single LLM ingress. Each tool has a typed JSON Schema
input and a deterministic numeric output. Numbers come from the same Python
packages used by the dashboard (ADR-0002). A 20-question golden-eval suite
gates releases.

## Consequences

### Positive

- Numeric correctness is enforced by code, not by prompt.
- Same answer regardless of LLM provider.
- Raw transactions never leave the host; the LLM only sees aggregated
  tool outputs.
- Eval suite makes regressions visible.

### Negative

- Every new question class needs a new tool or tool extension.
- Initial cost to design typed tool schemas.

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
- `mcp/` (planned)
- Issues #44–#49, #54
