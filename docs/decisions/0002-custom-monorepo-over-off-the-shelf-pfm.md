# 0002 — Custom monorepo over off-the-shelf PFM tools

- **Status:** Accepted
- **Date:** 2026-05-06
- **Deciders:** @autoditac
- **Tags:** infra, mcp, sim, tax

## Context and Problem Statement

Off-the-shelf personal-finance managers (Firefly III, Actual, Maybe, GnuCash,
Lunch Money, YNAB, Monarch, Portfolio Performance) cover budgeting and basic
net-worth tracking. Penge’s requirements go beyond that: multi-jurisdiction
tax simulation (DK Lagerbeskatning + ASK + PAL-skat; DE Vorabpauschale +
Teilfreistellung), 10-year FIRE projections in EUR and DKK in parallel,
PSD2 ingestion across DK and DE banks, a document vault with OCR + semantic
search, and an LLM-facing MCP layer with typed tools and golden-question
evals. We need to decide whether to extend an existing PFM or build a
purpose-built monorepo.

## Decision Drivers

- Tax accuracy: DK Lagerbeskatning and DE Vorabpauschale are not modeled by
  any existing OSS PFM at the depth we need (tax-lot tracking, ASK 17 %,
  Aktiesparekonto, Teilfreistellung classes).
- LLM/MCP first-class: typed Python tools with deterministic numeric output
  and a 20-question eval suite.
- FIRE projections beyond budgeting (Monte Carlo / scenario engine).
- Single owner, long horizon: prefer code we fully understand.
- Reversibility via Parquet exports (see ADR-0001).

## Considered Options

1. **Custom monorepo** — Python (uv) + TypeScript (pnpm) + dbt + Streamlit + MCP, single repo.
2. **Extend Firefly III / Actual** — fork an existing PFM, add tax + FIRE + MCP modules.
3. **Best-of-breed federation** — Portfolio Performance (holdings) + Actual (budgets) + custom tax scripts, glued together.

## Decision

We chose **Option 1: a custom monorepo**.

The repository hosts the ingestion connectors, dbt models, FIRE simulation
engine, tax modules (`tax/dk`, `tax/de`), MCP server, Streamlit dashboard,
and MkDocs site as siblings, with shared CI, ADRs, and Conventional Commits.

## Consequences

### Positive

- One mental model, one CI pipeline, one issue tracker, one ADR log.
- Tax and FIRE logic are first-class, version-controlled, and testable
  against golden fixtures.
- MCP tools can call directly into the same Python packages used by the
  dashboard — no API translation layer.
- No upstream PFM constraints on the data model.

### Negative

- We rebuild basics (categorization, budgeting UI) instead of inheriting them.
- Higher initial implementation cost; offset by removing fork/merge tax
  with an upstream we would diverge from anyway.

### Neutral

- We can still import from / export to other PFMs via CSV/QIF for
  reversibility.

## Alternatives in detail

### Extend Firefly III / Actual

Rejected: their data models are budgeting-centric; tax-lot tracking and
DK/DE-specific tax mechanics would force invasive forks, and their LLM
stories are not aligned with MCP.

### Best-of-breed federation

Rejected: gluing three apps via CSV exports yields stale, inconsistent
state and no shared identity layer for documents ↔ transactions ↔ holdings.

## Links

- ADR-0001 (stack)
- ADR-0005 (LLM via MCP only)
