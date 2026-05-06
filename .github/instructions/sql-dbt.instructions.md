---
applyTo: "dbt/**"
---

# dbt + SQL instructions

## Project

- Adapter: `dbt-duckdb`. Source data is read from Postgres via the `postgres_scanner` extension or via a periodic Parquet export.
- Models live under `dbt/models/`:
  - `staging/` — `stg_<source>__<table>.sql`. One model per source table. **Only renaming, casting, and lightweight cleanup.**
  - `intermediate/` — `int_<purpose>.sql`. Reusable joins and business logic.
  - `marts/` — `mart_<entity_or_metric>.sql`. The final analytics tables consumed by dashboards and the MCP server.
- Materializations: staging = `view`, intermediate = `ephemeral` or `view`, marts = `table` or `incremental`.

## Naming

- Tables and columns: `snake_case`.
- Money columns: `<concept>_amount_<ccy>` where `<ccy>` is `eur`, `dkk`, or `native` for original-currency.
- Date columns: `<concept>_date` (truth date) and `<concept>_at` for timestamps.
- Booleans: prefix with `is_`, `has_`, or `was_`.

## SQL style

- Format with `sqlfluff` (config in `dbt/.sqlfluff`). Run in pre-commit.
- Lower-case keywords, leading commas, one column per line in `SELECT`.
- CTEs over nested subqueries. Final CTE is named `final` and the model ends with `select * from final`.
- No `SELECT *` outside the trivial `final` projection.
- Always qualify column names with the table or alias.

## Tests & docs

- **Every model** has a sibling `schema.yml` with:
  - A `description` of what the model represents in business terms.
  - A `description` for every column.
  - At minimum, primary-key columns have `not_null` and `unique` tests.
  - Foreign keys have `relationships` tests.
- Add custom data tests under `dbt/tests/` for invariants (e.g. "FX-rate table has no gaps > 7 days").

## Idempotency

- Models must be idempotent: running `dbt build` twice produces the same output.
- Incremental models require a `unique_key` and a tested merge strategy.

## Dependencies

- Use `dbt_utils` for cross-DB helpers.
- Add new packages via `packages.yml`; pin to a minor version.
