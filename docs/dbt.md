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
  `mart_net_worth_daily` (issue #24) is the first.

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

Reviewers should reject speculative additions; only add a package
when a specific model needs a specific macro from it.
