# dbt analytics layer

Penge uses [dbt](https://docs.getdbt.com/) for analytics modelling
on top of the operational Postgres schema produced by Alembic. dbt
sits **read-only** on the `public` schema and writes its own
artefacts into the `staging` and `marts` schemas inside the same
database.

## Layout

```text
dbt/
├── dbt_project.yml         # project config; profile = penge
├── profiles.yml            # env-var driven; safe to commit
├── packages.yml            # third-party dbt packages (currently none)
└── models/
    ├── staging/
    │   └── _sources.yml    # raw operational tables declared here
    └── marts/              # business logic (net worth, cash flow, …)
```

- `models/staging/` — 1:1 cleaned views over raw tables. One
  `stg_<source>__<table>.sql` file per raw table we actually use,
  plus a sibling `schema.yml` with column tests.
- `models/marts/` — business-logic models materialised as tables.
  `mart_net_worth_daily` (issue #24) is the first; see
  [Marts](#marts) below.

## Connection

`profiles.yml` resolves the connection from `PG*` env vars:

| Variable      | Default     |
|---------------|-------------|
| `PGHOST`      | `localhost` |
| `PGPORT`      | `5432`      |
| `PGUSER`      | `penge`     |
| `PGPASSWORD`  | `penge`     |
| `PGDATABASE`  | `penge`     |
| `PGSSLMODE`   | `prefer`    |

Local development against the compose Postgres needs no overrides;
the defaults match `compose.yaml`.

## Running locally

```bash
# 1. Bring up Postgres + apply migrations.
docker compose up -d postgres
uv run --group db alembic upgrade head

# 2. Install the dbt group.
uv sync --group dbt

# 3. Smoke-test the project.
uv run --group dbt dbt deps  --project-dir dbt --profiles-dir dbt
uv run --group dbt dbt parse --project-dir dbt --profiles-dir dbt
uv run --group dbt dbt build --project-dir dbt --profiles-dir dbt

# 4. Inspect generated docs (optional).
uv run --group dbt dbt docs generate --project-dir dbt --profiles-dir dbt
uv run --group dbt dbt docs serve    --project-dir dbt --profiles-dir dbt
```

`dbt build` runs models, snapshots, seeds, and tests in dependency
order. With zero models it is a successful no-op that still
validates the project is parseable and the warehouse is reachable.

## CI

The [`dbt` workflow](https://github.com/autoditac/Penge/blob/main/.github/workflows/dbt.yml) runs the same
`alembic upgrade head` → `dbt deps` → `dbt parse` → `dbt build`
sequence against an ephemeral Postgres on every PR that touches
`dbt/`, `migrations/`, `pyproject.toml`, `uv.lock`, or the workflow
itself. It is not yet on the protected-branch required-checks list;
add it once the first model lands and we have confidence in the
build time.

## Conventions

- **Source schema is `public`**, declared once in
  `models/staging/_sources.yml`. Reference it with
  `{{ source('raw', 'transaction') }}`, never with raw
  `public.transaction`.
- **Staging models** are views (`+materialized: view`).
- **Mart models** are tables (`+materialized: table`).
- **Schema names** are dbt-suffixed: staging models land in
  `analytics_staging`, marts in `analytics_marts`. (dbt's default
  `<target_schema>_<config_schema>` rule with `target schema =
  analytics`.)
- **SQL style**: snake_case identifiers, leading commas, CTEs
  preferred over subqueries. A `.sqlfluff` config will land
  alongside the first model.
- **Tests**: every staging model declares `not_null` on its primary
  key in `_schema.yml`. Mart-level invariants get bespoke
  `tests/` SQL.

## Adding a package

```bash
echo "packages:
  - package: dbt-labs/dbt_utils
    version: [\">=1.2.0\", \"<2.0.0\"]" > dbt/packages.yml
uv run --group dbt dbt deps --project-dir dbt --profiles-dir dbt
```

Reviewers should reject speculative additions; only a

## Marts

### `mart_net_worth_daily`

Daily net-worth time series at account / entity level, in three
currencies in parallel: account currency, EUR, and DKK
(per [ADR-0004](decisions/0004-eur-and-dkk-shown-in-parallel.md)).

**Grain.** One row per `(account_id, as_of)`.

**Mechanics.**

1. Build a daily date spine spanning the active range of
   `raw.holding_snapshot` (`min(as_of)` … `max(as_of)`).
2. For every `(account, instrument)` pair ever observed,
   forward-fill the most recent `market_value` snapshot at-or-before
   each spine date. Cash is materialised as `instrument.kind =
   'cash'` synthetic instruments with `quantity = saldo`,
   `price = 1` per [ADR-0008](decisions/0008-nordnet-account-modelling.md),
   so the same panel covers cash and securities uniformly.
3. Sum per `(account_id, as_of)` to derive the account-currency
   balance.
4. Convert to EUR and DKK using the snapshot-date ECB FX rate
   (`raw.fx_rate`, `base_ccy = 'EUR'`), forward-filled across
   weekends/holidays so every spine date has a non-null rate
   whenever the source has at least one rate at-or-before it.

**Columns.** `entity_id`, `account_id`, `account_currency`,
`as_of`, `balance_acct_ccy`, `balance_eur`, `balance_dkk`. See
`dbt/models/marts/_mart_net_worth_daily__schema.yml` for column
docs and tests.

**Custom tests.**

- `mart_net_worth_daily__monotonic_date_index` — per `account_id`,
  the set of `as_of` dates between `min(as_of)` and `max(as_of)`
  must form a contiguous daily series.
- `mart_net_worth_daily__no_fx_gaps` — every row with a non-null
  `balance_acct_ccy` must also have non-null `balance_eur` and
  `balance_dkk`.

**v1 scope.** Balance time series only. Per-transaction cashflow
FX attribution (using `transaction.fx_rate` at booking time) is
out of scope here and will land with the cashflow mart.dd a package
when a specific model needs a specific macro from it.
