# Architecture Decision Records (ADRs)

This directory captures the **why** behind significant decisions in Penge.

## When to write one

See the [`write-adr` skill](https://github.com/autoditac/Penge/blob/main/.github/skills/write-adr/SKILL.md). Roughly: any change that adds/replaces a service, library, or external dependency, alters the data model, changes a tax-rule interpretation, alters an integration pattern, or affects a security boundary.

## Format

We use the [MADR](https://adr.github.io/madr/) template — see [`adr-template.md`](adr-template.md).

## Index

<!-- Keep this list sorted by ADR number. -->

| #    | Title                                                                                        | Status   |
|------|----------------------------------------------------------------------------------------------|----------|
| [0001](0001-self-hosted-postgres-duckdb-stack.md) | Self-hosted Postgres + DuckDB stack over a managed lakehouse | Accepted |
| [0002](0002-custom-monorepo-over-off-the-shelf-pfm.md) | Custom monorepo over off-the-shelf PFM tools                 | Accepted |
| [0003](0003-hybrid-ingestion-psd2-and-csv-pdf.md) | Hybrid ingestion: PSD2 (GoCardless) + CSV/PDF parsers        | Superseded by [0026](0026-retire-gocardless-for-enable-banking.md) |
| [0004](0004-eur-and-dkk-shown-in-parallel.md) | EUR and DKK shown in parallel; no single base currency       | Accepted |
| [0005](0005-llm-access-via-mcp-only.md) | LLM access exclusively via MCP server with typed tools       | Accepted |
| [0006](0006-trunk-based-conventional-commits-adrs.md) | Trunk-based development with Conventional Commits and ADRs   | Accepted |
| [0007](0007-initial-relational-data-model.md) | Initial relational data model                                | Accepted |
| [0008](0008-nordnet-account-modelling.md) | Nordnet account modelling: kinds, multi-currency cash, ASK   | Accepted |
| [0026](0026-retire-gocardless-for-enable-banking.md) | Retire GoCardless; standardize on Enable Banking for PSD2 | Accepted |
| [0027](0027-liquid-depot-simulation-model.md) | Liquid depot simulation model (ASK + frie midler, Lager/Realisation) | Proposed |
| [0028](0028-sim-payout-model.md) | Decumulation payout model: annuity factor + PMT | Proposed |
| [0033](0033-reporting-first-react-webui.md) | Reporting-first React WebUI | Proposed |
| [0034](0034-application-container-images.md) | Application container images in CI and releases | Proposed |
| [0035](0035-fastapi-read-api.md) | FastAPI read API as the WebUI data layer | Proposed |
