# 0001 — Self-hosted Postgres + DuckDB stack over a managed lakehouse

- **Status:** Accepted
- **Date:** 2026-05-06
- **Deciders:** @autoditac
- **Tags:** infra, security

## Context and Problem Statement

Penge is a private, single-user personal-finance and FIRE platform. It must
hold sensitive financial data (PSD2 transactions, brokerage holdings, tax
documents, salary slips) for many years and serve interactive analytics, dbt
transformations, and an LLM-facing MCP layer. We need a primary store for
mutable operational data and an analytics layer for ad-hoc queries, dashboards,
and projections, without taking on managed-cloud cost or exposing raw financial
data to a third-party provider.

## Decision Drivers

- Sovereignty: financial + tax data must stay on hardware we control.
- Cost: zero recurring SaaS fees; runs on a home server / single VPS.
- Operational simplicity: one developer, one operator — must be runnable and
  restorable from a Docker Compose file.
- Analytics ergonomics: fast ad-hoc OLAP for net-worth, allocation, tax
  simulations, and dbt models.
- Reversibility: data formats must be portable (SQL dumps, Parquet) so we are
  not locked in.

## Considered Options

1. **Postgres 17 (operational) + DuckDB / Parquet (analytics) + dbt-duckdb** — self-hosted via Docker Compose.
2. **Managed lakehouse (Snowflake / BigQuery / Databricks)** — cloud OLAP with hosted SQL.
3. **Postgres only** — operational and analytics on the same engine, no DuckDB.
4. **SQLite + Parquet** — single-file operational DB, DuckDB for analytics.

## Decision

We chose **Option 1: Postgres 17 + DuckDB/Parquet + dbt-duckdb**.

Postgres 17 is the source of truth for normalized, mutable entities (accounts,
transactions, holdings, documents, FX rates, tax-lots). DuckDB reads exported
Parquet snapshots and runs dbt models for analytics, projections, and the
Streamlit dashboard. The Compose stack is the deployment unit.

## Consequences

### Positive

- Full data sovereignty; no third-party processor for financial records.
- No recurring SaaS spend; total cost ≈ home-server power.
- DuckDB gives near-warehouse OLAP performance on a laptop-class machine.
- Parquet snapshots are a portable, vendor-neutral archive format.
- dbt-duckdb is a proven, well-supported toolchain.

### Negative

- We own backups, upgrades, monitoring, and disaster recovery.
- Two engines to learn and version (Postgres + DuckDB) instead of one.
- Concurrent multi-user analytics is not a goal; DuckDB is single-process.

### Neutral

- pgvector (in Postgres) covers semantic-search needs without an extra service.
- Migrating off this stack later is feasible because data lives in standard
  Postgres dumps and Parquet files.

## Alternatives in detail

### Managed lakehouse

Rejected: cost (≥ tens of EUR/month idle), data residency, and the requirement
to ship raw transaction-level data to a US/EU SaaS provider conflict with the
sovereignty driver.

### Postgres only

Rejected: workable but slower for the column-oriented aggregations central to
net-worth, allocation, and FIRE projections; also forces analytics queries to
contend with operational load.

### SQLite + Parquet

Rejected: SQLite lacks pgvector and concurrent-writer guarantees we want for
the ingestion pipeline and document vault.

## Links

- ADR-0002 (custom monorepo over off-the-shelf PFM)
- `compose.yaml`
- `pyproject.toml`
