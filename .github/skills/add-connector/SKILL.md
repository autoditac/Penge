# Skill: add-connector

Recipe for adding a new ingestion source (bank, broker, pension provider, ...).

## When to use

User asks to "add support for <source>" or "ingest data from <source>". The source produces transactions, holdings, prices, or statements that should land in the canonical Penge schema.

## Preconditions

- An issue exists describing the source, its data shape, and its priority. If not, **create the issue first** and stop.
- The source's data shape is understood: list of fields, sample (anonymized) export, refresh cadence.
- The data classification is known: PSD2 stream, CSV download, PDF statement, web scrape (last resort).

## Steps

1. **Branch:** `feat/<issue-number>-<source>-connector`.
2. **Scaffold module:** `apps/ingest/connectors/<source>/` with:
   - `__init__.py`
   - `client.py` (fetch / read raw data)
   - `parser.py` (raw → Pydantic models)
   - `loader.py` (Pydantic → SQLAlchemy upsert into `transaction`, `holding_snapshot`, etc.)
   - `tests/` with synthetic fixtures.
3. **Pydantic models** for each raw record type. Strict, no `Any`. Validate on parse.
4. **Mapping table** — write the source-field → canonical-field mapping table now, in `docs/connectors/<source>.md`. Implement to match.
5. **Idempotency:** all loads are upserts keyed on a deterministic source-derived key. Re-running the loader produces zero changes if data is unchanged.
6. **dbt staging model:** `dbt/models/staging/stg_<source>__<entity>.sql` with `schema.yml` (description + column docs + `not_null`/`unique` tests).
7. **Tests:**
   - Unit tests for the parser using synthetic fixtures.
   - Integration test that loads a fixture into a transactional Postgres and asserts the resulting rows.
   - dbt tests on the staging model run via `dbt build` in CI.
8. **Runbook entry:** if this connector requires manual steps (uploading a CSV, refreshing a token), add `docs/runbook/connector-<source>.md`.
9. **Connector docs page:** complete `docs/connectors/<source>.md` (auth, cadence, quirks, mapping, fallback).
10. **Update `Justfile`:** add `just ingest-<source>` if the connector has a CLI entrypoint.
11. **PR:** template, `Closes #N`, screenshots/log excerpts of a successful run on synthetic data.

## Definition of done (skill-specific)

- Synthetic-fixture unit tests pass.
- Integration test against Postgres passes.
- dbt staging model + schema.yml exists and `dbt build` is green.
- `docs/connectors/<source>.md` is complete (no TODOs).
- Idempotency verified by running the loader twice in the integration test.
- No real data committed.

## Common pitfalls

- **Floats for money.** Use `Decimal`. The Pydantic model declares `Decimal`, the SQL column is `Numeric`.
- **Naïve datetimes.** Always parse to UTC `datetime` with tz info.
- **Mixed currencies.** Each record carries its native currency; conversion happens later in dbt or analytics.
- **Hidden state.** No file-system caches under `~/`. Use `data/cache/` (gitignored).
