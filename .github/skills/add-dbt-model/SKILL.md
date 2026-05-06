# Skill: add-dbt-model

Recipe for adding a dbt model (staging, intermediate, or mart).

## When to use

User asks to "expose <metric>", "compute <aggregate>", or a new analytics need surfaces. Anything that consumes from Postgres tables and produces a tabular analytical artifact lives in dbt.

## Decide the layer

| Layer          | Purpose                                              | Materialization        |
|----------------|------------------------------------------------------|------------------------|
| `staging/`     | One model per source table; rename, cast, light clean | `view`                 |
| `intermediate/`| Reusable joins and business logic                    | `ephemeral` or `view`  |
| `marts/`       | Final tables consumed by dashboards / MCP server     | `table` or `incremental` |

If unsure, write the staging layer first; never put business logic in staging.

## Steps

1. **Branch:** `feat/<issue-number>-<short-slug>`.
2. Place the model file in the correct layer with the right prefix:
   - `stg_<source>__<entity>.sql`
   - `int_<purpose>.sql`
   - `mart_<entity_or_metric>.sql`
3. Write the SQL following [the SQL/dbt instructions](../../instructions/sql-dbt.instructions.md): leading commas, CTEs, final CTE named `final`, no `SELECT *` except the final projection.
4. **Schema docs (`schema.yml`):**
   - Top-level model description in business terms.
   - Description for **every** column.
   - `not_null` and `unique` on PK columns.
   - `relationships` tests on FKs.
5. **Custom tests** (`dbt/tests/`): add invariants where they exist (e.g. "sum of holdings equals account balance", "FX-rate gaps < 7 days").
6. **Run locally:** `just dbt build --select <model>` and `just dbt test --select <model>`.
7. **Idempotency check** for incremental models: run twice, assert second run produces zero changed rows when input is unchanged.
8. **Update consumers** (dashboard, MCP tool, report) in the **same PR** if the model schema changes or is new.
9. **PR** with description of the metric, sample query/output (anonymized), and `Closes #N`.

## Naming reminders

- Money columns: `<concept>_amount_<eur|dkk|native>`.
- Date: `<concept>_date`. Timestamp: `<concept>_at`.
- Booleans: `is_`, `has_`, `was_`.

## Common pitfalls

- Forgetting to add `schema.yml`. CI will pass; reviewers will not.
- Mixing currencies without explicit FX conversion.
- Putting business logic in `staging/` — it belongs in `intermediate/` or `marts/`.
- Incremental model without a `unique_key` — produces duplicates.
