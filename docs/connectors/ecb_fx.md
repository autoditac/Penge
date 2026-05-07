# ECB daily FX rates

Source: [European Central Bank `eurofxref` XML feed][ecb-feed].

EUR is always the base currency; the ECB publishes one row per quote
currency per business day around 16:00 CET. The loader populates the
[`fx_rate`](../decisions/0007-initial-relational-data-model.md) table.

[ecb-feed]: https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml

## Feeds

| Feed | URL | Use |
|---|---|---|
| Daily | `eurofxref-daily.xml` | Cron refresh — latest business day only |
| 90-day | `eurofxref-hist-90d.xml` | Catch-up after a short outage |
| Historical | `eurofxref-hist.xml` | One-time backfill since 1999 |

## CLI

The package installs a `penge-ecb-fx` entry point:

```bash
# Manual run (writes to the DATABASE_URL Postgres):
uv run --group db penge-ecb-fx --latest
uv run --group db penge-ecb-fx --90d
uv run --group db penge-ecb-fx --since 2014-01-01

# Parse-only smoke check, no DB write:
uv run --group db penge-ecb-fx --latest --dry-run
```

The connection string comes from `DATABASE_URL`, falling back to the
`POSTGRES_*` env vars used by `compose.yaml` for local dev.

## Idempotency

Writes use `INSERT ... ON CONFLICT (as_of, base_ccy, quote_ccy) DO UPDATE`
against the `ux_fx_rate__as_of_base_quote` constraint, so re-running the
loader is safe and only rewrites the `rate` and `source` columns when the
upstream value has changed.

## Scheduled refresh

[`.github/workflows/ecb-fx.yml`](https://github.com/autoditac/Penge/blob/main/.github/workflows/ecb-fx.yml)
runs on a weekday cron (16:30 UTC) plus `workflow_dispatch`. It is gated
by the repository variable `PENGE_FX_INGEST_ENABLED`:

- Cron triggers only fire when the variable is set to `'true'`.
- `workflow_dispatch` always works (manual ad-hoc backfills).

The workflow expects a `DATABASE_URL` secret pointing at the operational
Postgres. Set the variable + secret once that infra exists; until then,
run the loader locally.

## Backfill

Once-off historical load:

```bash
uv run --group db penge-ecb-fx --since 2014-01-01
```

This pulls the full historical XML (~5 MB), filters to entries on or
after the cutoff, and upserts in a single transaction.
