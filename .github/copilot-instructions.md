# GitHub Copilot — repository instructions

These instructions apply to **all** files in this repository.

## Mindset

- Penge is a **trustworthy data platform**, not a script. Correctness > cleverness > speed.
- Treat every change as if it will be reviewed by a future engineer who has never seen this code.
- Prefer **boring, explicit, well-typed** code over clever abstractions.

## Workflow rules

1. Never commit directly to `main`. Always work on a feature branch and open a PR.
2. Every PR must close or reference an issue (`Closes #N` / `Refs #N`).
3. PR titles and squash-merge commits use [Conventional Commits](https://www.conventionalcommits.org/).
4. Every code change includes tests. Every behavioral or architectural change includes documentation.
5. Architectural changes require an ADR in `docs/decisions/` using the MADR template.
6. Migrations are reversible (tested `alembic upgrade && alembic downgrade`).
7. The full Definition of Done is in [CONTRIBUTING.md](../CONTRIBUTING.md).

## Toolchain — never deviate

- Python: `uv` only (`uv add`, `uv run`, `uv sync`). Never `pip`, never `python -m venv`.
- TypeScript: `pnpm` only. Never `npm`, never `yarn`.
- Tasks: add to `Justfile`, do not document ad-hoc shell commands.
- Pre-commit hooks must pass before any commit.

## What never to do

- Do **not** commit anything in `data/`, `*.env`, `*.csv`, `*.pdf`, `*.parquet`, real account numbers, real names of counterparties, or salary numbers.
- Do **not** add a dependency without recording why an existing one cannot be used.
- Do **not** use `latest` tags for Docker images or Action versions; pin by digest/SHA.
- Do **not** silently change a tax rule, FX source, or asset-class definition. Open an ADR.
- Do **not** introduce a new currency-handling pattern; EUR and DKK are both first-class everywhere.
- Do **not** weaken type hints (`Any`, `# type: ignore`) without a code-comment justification.
- Do **not** print to stdout outside CLI entrypoints — use `structlog`.

## Language rules

- Code, identifiers, code-comments, commit messages, PR titles, and ADRs are **English**.
- User-facing prose in `docs/` may be German or English (mark accordingly with file suffix or front-matter).
- Avoid mixing languages within a single file unless it is a translation pair.

## Working with sensitive data

- All test fixtures must be **synthetic or anonymized**. Never copy a real statement into `tests/`.
- The MCP server is the only sanctioned LLM data path. Do not add new ad-hoc LLM integrations that read raw data.

## When asked to "just make it work"

Push back politely. Propose a small, traceable change instead. The cost of a bad shortcut here is a wrong number on a tax filing or a leaked statement.
