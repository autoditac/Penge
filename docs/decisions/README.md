# Architecture Decision Records (ADRs)

This directory captures the **why** behind significant decisions in Penge.

## When to write one

See the [`write-adr` skill](../../.github/skills/write-adr/SKILL.md). Roughly: any change that adds/replaces a service, library, or external dependency, alters the data model, changes a tax-rule interpretation, alters an integration pattern, or affects a security boundary.

## Format

We use the [MADR](https://adr.github.io/madr/) template — see [`adr-template.md`](adr-template.md).

## Index

<!-- Keep this list sorted by ADR number. -->

| #    | Title                                                       | Status   |
|------|-------------------------------------------------------------|----------|
| 0001 | Self-hosted Postgres + DuckDB stack over a managed lakehouse | Proposed |
| 0002 | Custom monorepo over off-the-shelf PFM tools                 | Proposed |
| 0003 | Hybrid ingestion: PSD2 (GoCardless) + CSV/PDF parsers        | Proposed |
| 0004 | EUR and DKK shown in parallel; no single base currency       | Proposed |
| 0005 | LLM access exclusively via MCP server with typed tools       | Proposed |
| 0006 | Trunk-based development with Conventional Commits and ADRs   | Proposed |

ADRs are introduced in PR `docs(adr): bootstrap ADRs 0001-0006`.
