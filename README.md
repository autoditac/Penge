# Penge

Private personal-finance & FIRE-modeling platform for a DK/DE household.

> **Penge** (Danish for *money*).

## What this is

A self-hosted data platform that:

- Ingests transactions, holdings, and statements from DE & DK banks, brokers, and pensions (GLS, Evangelische Bank, Lunar, Nordnet, PFA, Growney).
- Tracks net worth in EUR and DKK in parallel, including holdings, pensions, real estate, and cash.
- Computes Danish *lagerbeskatning* (mark-to-market) and German *Vorabpauschale* tax positions for the year.
- Runs Monte-Carlo FIRE projections and scenario simulations (house purchase, work-time reduction, ...).
- Stores statements in a document vault and exposes the whole dataset to LLMs through a typed Model Context Protocol (MCP) server.

## Status

🚧 Phase 0 — Foundations. See the [project backlog](https://github.com/users/autoditac/projects) and milestones.

## Repository conventions

- Trunk-based with short-lived feature branches; everything lands on `main` via PR.
- [Conventional Commits](https://www.conventionalcommits.org/) are enforced.
- Architectural decisions are recorded as ADRs in [`docs/decisions/`](docs/decisions/).
- See [CONTRIBUTING.md](CONTRIBUTING.md) for the full development flow.
- Coding agents (Copilot, Codex, Claude Code, Cursor) follow the rules in [`AGENTS.md`](AGENTS.md) and [`.github/`](.github/).

## Quick start (once Phase 0 lands)

```bash
just bootstrap     # install toolchain
just up            # docker compose up
just test          # run all tests
just docs          # serve docs locally
```

## Layout

```
apps/        # ingestion workers, simulation engine, web UI, MCP server
dbt/         # analytics models (staging → marts)
migrations/  # Alembic migrations for Postgres
docs/        # MkDocs site, ADRs, runbooks, connector docs
deploy/      # compose & Ansible manifests for the home server
data/        # local data (gitignored, mounted from Nextcloud)
.github/     # CI, agent customization, templates
```

## License

Private. All rights reserved. Not for redistribution.
