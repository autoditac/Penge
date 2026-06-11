# 0035 — FastAPI read API as the WebUI data layer

- **Status:** Proposed
- **Date:** 2026-06-11
- **Deciders:** @autoditac
- **Tags:** web, api, security, data

## Context and Problem Statement

The React WebUI ([ADR-0033](0033-reporting-first-react-webui.md)) currently
renders synthetic fixture data only.
The deterministic numbers it must show live in the dbt marts
(`analytics_marts.mart_net_worth_daily`, `mart_cashflow_daily`) and are read
today by two consumers: the Streamlit dashboard (direct SQL via SQLAlchemy)
and the MCP server (AI-facing tools, ADR-0005).
The browser cannot and should not open SQL connections, so the WebUI needs a
typed HTTP layer over the marts before any real-data dashboard work
(issues #203, #204) can start.

## Decision Drivers

- The parsers, marts, masking helpers, and simulation engine are all Python;
  the API should reuse them, not re-implement them.
- The TypeScript client must be generated from a reviewable contract so the
  UI and API cannot drift silently.
- Server-side masking: raw IBANs and account-number suffixes must never reach
  the browser (same rule the Streamlit layer applies at render time).
- EUR and DKK stay first-class in every response; no silent base currency.
- Money precision: amounts are `numeric(20, 4)` in Postgres and must not pass
  through binary floats on the way to the UI.

## Considered Options

1. **FastAPI app in `src/penge/api`** — Python, direct reuse of
   `penge.web.mask` / mart SQL, OpenAPI schema for client generation.
2. **Node/Express API in `apps/`** — TypeScript end-to-end, but every parser
   and mart access would shell out to Python or duplicate logic.
3. **Extend the MCP server with REST endpoints** — one process fewer, but it
   would mix the AI-facing tool boundary (ADR-0005) with general data access
   and couple the UI to the MCP runtime.

## Decision

Option 1: a **FastAPI application in `src/penge/api`**, served by uvicorn via
the `penge-api` entry point.

- **Read-only by design.** v1 ships `GET /net-worth/daily`,
  `GET /cashflow/daily`, `GET /allocation/current`, `GET /accounts`,
  `GET /meta/freshness`. No DML; write paths (staged imports, issue #207)
  require their own ADR.
- **Typed contract.** Pydantic response models generate the OpenAPI schema,
  which is committed at `docs/api/openapi.json`; a test fails CI when the
  artifact drifts. The WebUI generates its TS client from that file
  (issue #203).
- **Decimal on the wire.** Amounts serialise as JSON strings
  (`"1000.0000"`), never floats; the client converts explicitly at the edge.
- **Masking server-side.** `/accounts` applies `mask_iban` /
  `mask_account_name` before serialising; raw identifiers never leave the
  process.
- **Pagination everywhere.** Series endpoints take `limit`/`offset` with a
  hard cap, and default to a one-year window.
- **Local-only binding.** Defaults to `127.0.0.1:8000`; CORS allows the Vite
  dev origin only (overridable via `PENGE_API_CORS_ORIGINS`). Authentication
  is intentionally out of scope while the platform is single-household and
  LAN-bound — revisit before any remote exposure.

## Consequences

- Good: one Python codebase owns SQL, masking, and money handling; the UI
  consumes a generated client and cannot invent queries.
- Good: the committed OpenAPI artifact makes API changes reviewable in PRs.
- Bad: a third read path next to Streamlit and MCP — mitigated by keeping all
  three on the same marts and the same masking helpers.
- Bad: `fastapi` + `uvicorn` join the dependency tree (recorded in the `api`
  dependency group; rationale: no existing dependency provides an HTTP
  server with OpenAPI generation).

## Links

- [ADR-0005](0005-llm-access-via-mcp-only.md) — LLM access via MCP only
- [ADR-0004](0004-eur-and-dkk-shown-in-parallel.md) — EUR/DKK dual-currency rule
- [ADR-0033](0033-reporting-first-react-webui.md) — Reporting-first React WebUI
- Issue [#202](https://github.com/autoditac/Penge/issues/202), epic
  [#201](https://github.com/autoditac/Penge/issues/201)
