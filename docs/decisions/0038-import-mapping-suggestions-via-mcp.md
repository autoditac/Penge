# 0038 — Import mapping suggestions via the MCP server

- **Status:** Proposed
- **Date:** 2026-06-14
- **Deciders:** @autoditac
- **Tags:** mcp, llm, ingest, security, data

## Context and Problem Statement

The import wizard (issues #207/#208, ADR-0037) lets a household member upload
a statement, review staged rows, and commit them. Issue #209 asks for
AI-assisted categorization on top of that flow: per-row suggestions for the
spending/investment category, a normalized counterparty label, and a coarse
asset class.

ADR-0005 makes the MCP server the **only** sanctioned LLM data path, and
ADR-0035 keeps the FastAPI read surface free of side effects. Categorization
assistance must not become a back door: no ad-hoc LLM integration may read
uploads or staged rows, and nothing on the LLM path may write to the
database.

## Decision Drivers

- **ADR-0005 compliance.** The suggestion path must terminate at the MCP
  server; LLM hosts never see raw uploads, raw payloads stay masked.
- **Determinism and auditability.** A suggestion that changes between runs
  cannot be audited. Accept/reject decisions must reference stable output.
- **Read-only by construction.** The MCP Postgres pool forces
  `default_transaction_read_only = on`; suggestions must never write.
- **The wizard owns mutations.** Accepting a suggestion must reuse the
  existing `PATCH /imports/{id}/rows/{row_id}` endpoint and its
  re-validation, not a parallel write path.
- Suggestions should degrade gracefully: no rule match → no suggestion, and
  the wizard stays fully usable without the MCP server running.

## Considered Options

1. **A deterministic, rule-based MCP tool `suggest_import_mapping`** —
   reads staged rows over the read-only pool, maps canonical transaction
   kinds and DA/DE/EN keywords to a fixed category list, normalizes
   counterparty strings (whitespace collapsed, digits redacted), and
   keyword-matches asset classes. The LLM host reasons *on top of* this
   structured output.
2. **An LLM call inside the FastAPI app** ("just ask the model per row") —
   fast to build, but creates a second LLM integration outside MCP,
   violates ADR-0005, and produces non-reproducible suggestions.
3. **Client-side heuristics in the React wizard** — keeps data local but
   duplicates categorization logic outside the audited tool layer, is
   invisible to the eval harness, and cannot be reused by other MCP hosts.

## Decision Outcome

Chosen option: **1 — deterministic rule-based MCP tool**, because it is the
only option that keeps the LLM path sanctioned (ADR-0005), reproducible
(golden evals can pin exact outputs), and read-only (ADR-0035/0037 posture
survives).

Key properties:

- **Input:** `import_session_id` (UUID) + optional row `limit`. Only
  sessions with status `staged` are accepted; excluded rows are skipped.
- **Output:** per-row suggestions `{row_id, row_index, kind, field, value,
  confidence, reason}` with `field ∈ {category, counterparty, asset_class}`,
  validated by a strict Zod schema before leaving the server.
- **Masking:** every value and reason passes through the same value-pattern
  redaction as vault excerpts (IBAN, CPR, long digit runs → `[REDACTED]`).
- **Confidence tiers are rule strength**, not model probabilities: canonical
  kind map 0.9, definitional classes (balance→cash, scheme→pension) 0.95,
  keyword matches 0.5–0.7. No rule → no suggestion.
- **Writes stay in the wizard:** accepting a suggestion calls the existing
  import API PATCH endpoint (#210), which re-validates through the parser
  models.

### Consequences

- Good: the eval harness gains three golden questions (canonical-kind
  mapping, leak-freedom, determinism) that gate every release of the tool.
- Good: a future smarter generator (e.g. an embedding lookup) can replace
  the rule table behind the same wire schema and the same evals.
- Bad: rule-based suggestions are conservative — many rows get no
  suggestion at all. That is intentional; silence beats wrong guesses on a
  tax-relevant categorization.
- Bad: the MCP database role now needs `SELECT` on `import_session` /
  `import_row` in addition to the marts. Deployment grants must be updated
  alongside this change.

## Links

- Supersedes nothing; amends the tool surface documented in
  [ADR-0005](0005-llm-access-via-mcp-only.md).
- Builds on [ADR-0037](0037-staged-import-sessions.md) (staged sessions)
  and [ADR-0035](0035-fastapi-read-api.md) (read-only API posture).
- Tool reference: [docs/mcp/tools.md](../mcp/tools.md);
  eval coverage: [docs/mcp/evals.md](../mcp/evals.md).
- Issue #209; consumed by the wizard AI review layer in issue #210.
