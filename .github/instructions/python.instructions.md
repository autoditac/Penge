---
applyTo: "**/*.py"
---

# Python instructions

## Toolchain

- Use `uv` exclusively. `uv add <pkg>` to add deps; `uv run <cmd>` to run; `uv sync` to install. Never `pip`, never raw `venv`.
- Target Python version is the one in `.python-version` (currently 3.12). Do not introduce features beyond it.
- Lockfile (`uv.lock`) is committed and authoritative.

## Style

- Format with `ruff-format`. Lint with `ruff check`. Both run in pre-commit.
- Type-check with `mypy --strict`. Untyped functions are not allowed in new code.
- No `Any`, no `# type: ignore` without an inline reason: `# type: ignore[err-code]  # reason`.
- Imports: absolute within the project (`from penge.ingest.nordnet import ...`), no relative imports across packages.
- Line length: 100. Docstrings: Google style for public APIs.

## Boundaries

- All inputs at I/O boundaries (HTTP, file parse, CSV row, env var) are validated with **Pydantic** models. Never hand-parse.
- All public functions have explicit type hints, even when obvious.
- Use `pathlib.Path` for filesystem paths, never `str`.

## Logging

- Use `structlog` with JSON output in production, key-value in dev.
- Never `print()` outside `__main__` blocks of CLI entrypoints.
- Redact PII: account numbers, IBANs, salary amounts. Use a redaction processor.

## Errors

- Define a small set of domain exceptions (`PengeError`, `IngestError`, `TaxRuleError`, ...). Don't `raise Exception(...)`.
- Do not catch broad `Exception` except at the very top of a CLI/worker; re-raise with context elsewhere.

## Tests

- `pytest` with `pytest-cov`. Tests live under `tests/` mirroring the package layout.
- Fixtures are synthetic. No real bank statements in the repo.
- Database tests use a per-test transaction rollback against a real Postgres started by `compose.yaml`.
- Property-based tests (`hypothesis`) are encouraged for tax and FX calculations.

## CLIs

- Use `typer` or `click`. Always have `--help`, `--dry-run` where state is mutated, and `--verbose` toggling log level.

## Concurrency

- Default to synchronous code. Add `asyncio` only when there is a measured I/O reason (e.g. fan-out HTTP).
- For background workers, prefer a queue + simple worker process over ad-hoc threading.

## Database

- All writes go through SQLAlchemy ORM models. Raw SQL only in dbt (analytics) or migrations.
- Every read query that can return many rows uses pagination or streaming.
- Never store financial amounts as `float`. Use `decimal.Decimal` and the `Numeric` SQL type with explicit precision/scale.

## Money

- Amounts are `Decimal`, paired with a `currency: Currency` enum value. Never mix without explicit FX conversion.
- FX conversions go through a single `fx_service` that loads from `fx_rate` table; never inline rates in business logic.
