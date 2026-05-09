# Agent Working Contract

> This file is read by every coding agent operating in this repository (GitHub Copilot, Codex, Claude Code, Cursor, ...). It is the **single source of truth** for how to work here.

## Mission

Penge is a private personal-finance & FIRE-modeling platform for a DK/DE household. It must be **trustworthy** (correct numbers, reproducible builds, auditable changes) before it is fast or feature-complete.

## Hard rules

1. **No direct pushes to `main`.** Every change ships via a feature branch + PR.
2. **No commit may contain secrets or real financial data.** `data/`, `*.csv`, `*.pdf`, `*.parquet`, `.env*` are gitignored. Use anonymized fixtures in `tests/`.
3. **Every change ships with tests + docs.** See [CONTRIBUTING.md](CONTRIBUTING.md) for the Definition of Done.
4. **Architectural changes require an ADR** in `docs/decisions/` (MADR template).
5. **Conventional Commits are mandatory.** Commit messages and PR titles must conform; commitlint will reject violations.
6. **Migrations must be reversible.** Every Alembic upgrade has a tested downgrade.
7. **Reproducibility:** lockfiles are committed; Docker images are pinned by digest; GitHub Actions are pinned by SHA.
8. **Pin versions, never `latest`.** Applies to base images, action versions, package versions in lockfiles, and dbt packages.

## Toolchain (canonical)

- **Python:** managed by [`uv`](https://docs.astral.sh/uv/). Never call `pip` or `python -m venv` directly.
- **TypeScript / Node:** managed by [`pnpm`](https://pnpm.io/). Never call `npm` or `yarn`.
- **Tasks:** [`just`](https://just.systems/). Add a recipe to `Justfile` rather than documenting an ad-hoc command.
- **Pre-commit:** every contributor must have hooks installed (`just bootstrap` does this).
- **Containers:** Docker / Compose v2.

## Style & quality gates

- Linters/formatters: `ruff`, `ruff-format`, `mypy --strict`, `prettier`, `eslint`, `sqlfluff`, `markdownlint`.
- Tests: `pytest`, `vitest`, `dbt test`, `alembic upgrade/downgrade` round-trip.
- Security: `gitleaks`, Dependabot, `syft` SBOM, build-provenance attestation. (CodeQL is parked until the repo goes public or GitHub Advanced Security is purchased — SARIF upload requires code scanning to be enabled.)
- All of the above run in pre-commit and/or CI; both must pass before merge.

## File-scoped rules

When editing files in specific paths, additional rules apply:

| Path glob               | Rules                                                                 |
|-------------------------|-----------------------------------------------------------------------|
| `**/*.py`               | [`.github/instructions/python.instructions.md`](.github/instructions/python.instructions.md)         |
| `**/*.ts`, `**/*.tsx`   | [`.github/instructions/typescript.instructions.md`](.github/instructions/typescript.instructions.md) |
| `dbt/**`                | [`.github/instructions/sql-dbt.instructions.md`](.github/instructions/sql-dbt.instructions.md)       |
| `migrations/**`         | [`.github/instructions/migrations.instructions.md`](.github/instructions/migrations.instructions.md) |
| `docs/**`               | [`.github/instructions/docs.instructions.md`](.github/instructions/docs.instructions.md)             |

## Skills (recipes)

For recurring multi-step tasks, follow the recipe under `.github/skills/`:

- [`add-connector`](.github/skills/add-connector/SKILL.md) — add a new ingestion source.
- [`add-dbt-model`](.github/skills/add-dbt-model/SKILL.md) — add a staging/intermediate/mart model.
- [`write-adr`](.github/skills/write-adr/SKILL.md) — capture an architectural decision.
- [`release`](.github/skills/release/SKILL.md) — cut and deploy a release.

## Agent personas

Two agent modes are formalized for this repo:

- [`planner.agent.md`](.github/agents/planner.agent.md) — interviews the user, scopes work, breaks into issues.
- [`implementer.agent.md`](.github/agents/implementer.agent.md) — picks a single issue, implements, opens a PR, iterates to green.

A new conversation typically starts in *planner* mode and switches to *implementer* once an issue is well-defined.

## When you are unsure

1. Read the relevant ADRs in [`docs/decisions/`](docs/decisions/).
2. Check the runbook in [`docs/runbook/`](docs/runbook/).
3. If still unsure, **stop and ask** rather than guess. Open a `chore: question` issue or comment on the issue you are working on.

## Domain-specific knowledge

- **DK tax:** see [`docs/tax/dk.md`](docs/tax/dk.md). Lagerbeskatning is the dominant pattern for ETFs on the ABIS list.
- **DE tax:** see [`docs/tax/de.md`](docs/tax/de.md). Vorabpauschale + Teilfreistellung apply to the spouse's depot.
- **Currencies:** EUR and DKK are shown in parallel; FX from ECB. Never silently pick one as base.
- **Sources:** GLS Bank, Evangelische Bank, Lunar (PSD2 via GoCardless); Nordnet, PFA, Growney (CSV/PDF parsers); manual entries for cash and real estate.

## Out of scope

- Crypto tracking, automated trading/rebalancing, multi-tenant support, mobile apps, intraday prices.

If a request lands in an out-of-scope area, push back and propose a different approach.
