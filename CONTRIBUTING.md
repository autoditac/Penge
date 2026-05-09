# Contributing to Penge

This repository is a private personal project, but it is run with professional-grade engineering hygiene. The point of these rules is **traceability, reproducibility, and the ability to bring in another engineer (human or agent) at any time without onboarding chaos**.

## TL;DR

1. Pick (or open) an issue. Self-assign it.
2. Branch off `main`: `git switch -c feat/<issue-number>-short-slug`.
3. Implement with tests and docs. Add an ADR if your change is architectural.
4. Open a PR linked to the issue. Fill in the PR template.
5. CI must be green. Self-review (or peer review). Squash-merge with a [Conventional Commit](https://www.conventionalcommits.org/) title.
6. Delete the branch. Move the issue to *Done* on the project board.

## Branching

- Trunk-based: `main` is always releasable.
- Feature branches are short-lived (target: < 3 days).
- Naming: `<type>/<issue-number>-<kebab-slug>`, e.g. `feat/42-nordnet-csv-parser`, `fix/57-fx-rate-rounding`, `docs/12-runbook-monthly`, `chore/3-bump-actions`.
- Never push directly to `main`. Branch protection enforces this.

## Commits

We use [Conventional Commits](https://www.conventionalcommits.org/) and `commitlint`:

```text
<type>(<scope>)?: <subject>

<body>

<footer>
```

- `type`: `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `build`, `ci`, `perf`, `revert`.
- `scope` (optional): the affected component, e.g. `ingest`, `sim`, `tax`, `vault`, `mcp`, `web`, `dbt`, `infra`.
- Body explains *why*, not *what*.
- Footers: `Refs: #42`, `Closes: #42`, `BREAKING CHANGE: ...`.

Commits must be GPG/SSH-signed (`git config commit.gpgsign true`).

## Pull Requests

Every change to `main` goes through a PR. The PR template is mandatory.

### Definition of Done

A PR is ready to merge **only when all** apply:

- [ ] Linked to an issue (`Closes #N` or `Refs #N`).
- [ ] Tests added or updated. Coverage of touched code does not regress.
- [ ] Docs updated (user docs, runbook, ADR, or inline) if behavior, architecture, or operations changed.
- [ ] If architectural: a new ADR is included or referenced.
- [ ] Database migrations include a tested downgrade.
- [ ] No secrets in the diff (`gitleaks` and secret-scanning enforce this).
- [ ] CI green (lint, typecheck, tests, container build, dbt parse, sqlfluff).
- [ ] Self-reviewed (read your own diff in the GitHub UI before requesting review).

PRs are squash-merged. The PR title becomes the squashed commit message and **must** follow Conventional Commits.

## Architecture Decisions

If a PR introduces, replaces, or removes:

- a service, library, or external dependency
- a data-model concept (table, column, fact/dim)
- a tax-rule interpretation
- an integration pattern
- a security/privacy boundary

then the PR **must** include or reference an ADR in [`docs/decisions/`](docs/decisions/) using the [MADR](https://adr.github.io/madr/) template. ADR numbers are sequential. Status starts as `Proposed` and becomes `Accepted` on merge.

## Testing

- **Python:** `pytest` with `pytest-cov`. Unit tests live next to the code (`tests/`). Integration tests use a real Postgres + DuckDB via `compose.yaml`.
- **TypeScript (MCP):** `vitest`. Mock external services; do not call live APIs in tests.
- **dbt:** every model has a `schema.yml` with `not_null`, `unique`, and relationship tests where applicable. dbt tests run in CI against a seeded snapshot.
- **Migrations:** CI runs `alembic upgrade head && alembic downgrade base` on a fresh Postgres on every PR.
- **Tax logic:** golden-file tests reconciling computed values against hand-computed expectations from real (anonymized) årsopgørelse data.

## Local development

```bash
just bootstrap   # install toolchain (uv, pnpm, pre-commit hooks)
just up          # docker compose up Postgres + Adminer
just migrate     # alembic upgrade head
just test        # all tests
just lint        # ruff + mypy + eslint + sqlfluff + dbt parse
just docs        # serve mkdocs locally on :8000
```

## Documentation site

The docs site uses [MkDocs Material](https://squidfunk.github.io/mkdocs-material/). Sources live under `docs/`; build config in `mkdocs.yml`.

```bash
uv sync --group docs            # install mkdocs + extensions
uv run mkdocs serve             # local preview on :8000
uv run mkdocs build --strict    # what CI runs on every PR
```

The `docs` workflow builds `--strict` on every PR (broken links / orphan pages fail the build) and deploys to GitHub Pages on tag pushes (`v*`) by pushing to the `gh-pages` branch. The Pages site must be configured (one-time, in repo settings) to serve from the `gh-pages` branch root.

## Secrets

- Never commit plaintext secrets. `gitleaks` runs in pre-commit and CI.
- Local secrets in `.env` (gitignored); commit `.env.example` with safe defaults.
- Shared secrets are encrypted with `sops` + `age`; the `age` private key lives outside the repo.

## Pre-commit hooks

`just bootstrap` installs the toolchain and runs `pre-commit install --install-hooks && pre-commit install --hook-type commit-msg`. The configured hooks (see `.pre-commit-config.yaml`) are:

| Hook | Scope | Notes |
|---|---|---|
| `pre-commit-hooks` | all | large-files, merge-conflict, yaml/toml/json, trailing-whitespace, EOL, private-key, no-submodules |
| `gitleaks` | all | secret scan; same binary version as CI |
| `ruff` + `ruff-format` | Python | lint + format, fix on commit |
| `mypy --strict` | Python | type-check; activates once Python sources land |
| `sqlfluff-lint` | SQL | postgres dialect; refined via `.sqlfluff` in dbt phase |
| `prettier` | TS/TSX/JSON | markdown intentionally excluded — owned by `markdownlint` |
| `eslint` | TS/TSX | activates once the MCP TS workspace ships `eslint.config.js` |
| `markdownlint-cli2` | Markdown | uses `.markdownlint.jsonc`; same config as CI |
| `yamllint` | YAML | strict mode |
| `commitlint` | commit-msg | enforces Conventional Commits via `@commitlint/config-conventional` |

Run them all manually:

```bash
pre-commit run --all-files
```

## Reviewing your own work (solo mode)

Until a co-maintainer joins, you are both author and reviewer. The discipline:

1. After opening the PR, **wait at least one work-session** before merging non-trivial changes.
2. Re-read the diff in the GitHub UI, not the editor.
3. Treat your past self as a different reviewer: question every choice.
4. Run `just test && just lint` locally even if CI passed.

## Working with coding agents

When delegating to an agent (Copilot, Codex, Claude Code, Cursor):

- Point it at [`AGENTS.md`](AGENTS.md) and [`.github/copilot-instructions.md`](.github/copilot-instructions.md).
- Agents follow the same DoD as humans.
- Agent-authored PRs are clearly labeled (`agent:claude`, `agent:copilot`, ...) and reviewed with extra scrutiny.

## Questions?

Open a *Discussion* (once enabled) or a `chore`-typed issue with the question.
