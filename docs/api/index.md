# Read API

The read API is a small FastAPI application that exposes the analytics marts
to the [modern WebUI](../web/modern-webui.md) as typed JSON.
The reporting endpoints are strictly read-only and local-only; see
[ADR-0035](../decisions/0035-fastapi-read-api.md) for the decision record.
The sanctioned write surfaces are the staged import workflow under `/imports`
(see [ADR-0037](../decisions/0037-staged-import-sessions.md)), Enable Banking
consent and sync under `/connections` (see
[ADR-0040](../decisions/0040-in-app-enable-banking-consent-flow.md)), and the guarded
dbt-only refresh trigger under `/meta/refresh`
(see [ADR-0046](../decisions/0046-scheduled-enable-banking-net-worth-refresh.md)),
which reuses the scheduled worker's `DbtRunner`, lock, and pending marker
without touching any bank connection.
Import commits use that same lock and durable marker, so raw-table writes
cannot overlap a shadow dbt build.
The opt-in [household categorization API](household.md) adds guarded committed-transaction corrections, category trees, deterministic learning and explicit historical previews without changing source facts.

## Running it

```bash
just api-dev        # uvicorn on 127.0.0.1:8000 with auto-reload
just api-test       # pytest tests/api
just api-lint       # ruff + mypy --strict on the package
just api-openapi    # regenerate docs/api/openapi.json
```

The server binds `127.0.0.1:8000` by default.
Override with `PENGE_API_HOST` / `PENGE_API_PORT`, and the allowed CORS
origins with `PENGE_API_CORS_ORIGINS` (defaults to the Vite dev server).
Database resolution follows the same rules as every other component:
`DATABASE_URL` first, then the `POSTGRES_*` variables.

## Endpoints

| Endpoint              | Returns                                                          |
| --------------------- | ---------------------------------------------------------------- |
| `/net-worth/daily`    | Daily net worth, per account or summed (`group=total`)           |
| `/cashflow/daily`     | Daily inflow/outflow/net per account                             |
| `/allocation/current` | Latest-day allocation by `entity`, `currency`, or reporting kind |
| `/accounts`           | Masked account dimension with source kind, reporting kind, and latest import timestamp |
| `/meta/freshness`     | Latest data date and row count per mart, for staleness banners   |
| `POST /meta/refresh`  | Trigger a guarded dbt-only refresh (shadow build/test + atomic promotion); does not re-sync bank connections |

All series endpoints accept `since`, `until`, `account_id`, `entity_id`,
`limit`, and `offset`; the default window is one year.

## Returns and benchmarks (#206)

The returns endpoints expose the TWR/MWR engine (ADR-0039) for the
performance dashboard:

| Endpoint             | Returns                                                                |
| -------------------- | ---------------------------------------------------------------------- |
| `/returns/daily`     | Daily TWR factors and market values per scope (`account`, `asset_class`, `household`) |
| `/returns/summary`   | Cumulative + annualized TWR and annualized MWR (XIRR) per scope key, computed server-side via `penge.analytics` |
| `/returns/fees`      | Recorded fees per account and year (explicit fee bookings plus trade fee columns), EUR/DKK |
| `/benchmarks`        | Instruments with price history usable as benchmark series               |
| `/benchmarks/daily`  | Daily closes for one instrument (`instrument_id` required), native currency |

`/returns/daily` and `/returns/summary` take `scope` (default `household`)
plus the usual window parameters. Summary entries degrade per scope key: when
a window has no data or a currency leg lacks FX coverage, the entry carries
an `error` note instead of numbers, and `annualized_return` is `null` for
windows shorter than 30 days. Benchmark closes are **not** FX-adjusted — the
dashboard overlays them as normalized indexes to compare growth shape only.

## Import sessions

The `/imports` endpoints stage file uploads for review before anything is
written to the warehouse (upload → preview → fix/exclude rows → commit):

| Endpoint                                  | Action                                                        |
| ----------------------------------------- | ------------------------------------------------------------ |
| `POST /imports`                           | Upload a file (multipart); detects the source, stages rows   |
| `GET /imports`                            | List sessions with row counts                                 |
| `GET /imports/{id}`                       | Session detail with paginated staged rows                     |
| `PATCH /imports/{id}/rows/{row_id}`       | Edit a row payload (revalidated), toggle exclusion, or set mappings |
| `POST /imports/{id}/commit`               | Write staged rows through the existing connector loaders      |
| `POST /imports/{id}/suggestions`          | Proxy the MCP `suggest_import_mapping` tool (ADR-0038)        |
| `DELETE /imports/{id}`                    | Discard the session and delete the stored upload              |

Supported sources: `nordnet_transactions` and `nordnet_holdings` (UTF-16 CSV),
`growney` (Depotauszug PDF), `pfa` (Pensionsoversigt PDF), and
`manual_balances` (JSON).
Nordnet holdings use the original account/date filename and require an
account in the configured YAML.
Stage transactions first when a holding has no prior account-scoped instrument
history; an unmapped holding blocks the entire commit with `409` rather than
silently skipping a position.
Holdings-only commits never update transaction-derived cash snapshots.
Each committed holdings export is treated as complete for its account/date:
previously held securities missing from it receive zero snapshots, so sold
positions stop forward-filling; cash and other accounts remain untouched.
Excluding a holding during review means treating it as absent.
Correcting an omission by reimporting the same date restores its original
snapshot instead of retaining the zero.
Header-only Nordnet holdings exports can be committed as complete empty
snapshots when the complete provider header and filename are validated.
The session params include `empty_snapshot_confirmed: true` for that case;
commit revalidates the stored file and its upload checksum before zeroing.
It requires prior ISIN-mapped security snapshot history in the same account
on or before the export date; otherwise commit returns `409` and leaves the
session staged without changing account freshness.
Excluding every row of a nonempty export is rejected instead.
The staged source is `nordnet_holdings`, each row has kind `holding`, session
params carry `account_number` and `as_of`, and payloads use the
`ParsedHolding` fields (`name`, `quantity`, `market_value_dkk`, etc.).
The MCP mapping-suggestions tool accepts generic holding rows for this source,
but suggestions are optional and do not resolve missing ISIN mappings; clients
may omit the AI/suggestions step for holdings.
For staged Nordnet imports, `/accounts.last_updated_at` reflects the latest
successful commit with an included row for that account (including an
identical re-import), or a committed header-only holdings snapshot, not just
the raw row's first `created_at` timestamp.
CLI and other provider imports still use raw row creation timestamps.
`balance_changed_on` remains independent: a re-import without a changed
balance does not move that date.
See the [Nordnet connector](../connectors/nordnet.md) and
[ADR-0049](../decisions/0049-nordnet-holdings-only-imports.md).

Environment knobs: `PENGE_IMPORT_DIR` (upload storage, default
`data/imports`), `PENGE_IMPORT_MAX_BYTES` (default 25 MiB),
`PENGE_IMPORT_SESSION_TTL_DAYS` (default 7; stale staged sessions expire
lazily), and `PENGE_NORDNET_ACCOUNTS_CONFIG` (accounts YAML required to
commit Nordnet sessions).

### AI mapping suggestions

`POST /imports/{id}/suggestions` spawns the configured MCP server, calls
its `suggest_import_mapping` tool, and returns the structured suggestion
list unchanged — the API holds no categorization rules of its own
(ADR-0038, ADR-0005). The endpoint answers `503` while
`PENGE_MCP_SUGGEST_COMMAND` is unset (e.g.
`node apps/mcp/dist/index.js`) or the server is unreachable, and `502`
when the tool itself rejects the call; the wizard degrades to manual
review in both cases. `PENGE_MCP_SUGGEST_TIMEOUT_SECONDS` (default 30)
bounds one call.

Accepted suggestions are written back through the row PATCH as
`mappings` (allowed keys `category`, `counterparty`, `asset_class`)
plus `suggested_by`; the server stamps `accepted_at` when
`suggested_by` is present and clears both for manual mappings. An
empty `mappings` object is a manual clear: it removes all mappings and
any AI provenance. Mappings live next to the payload and never modify
it, so commit behavior is unchanged.

## Guarded dbt-only refresh (#285)

`POST /meta/refresh` lets the WebUI pull the next scheduled net-worth refresh
forward without waiting for the timer and without re-syncing any bank
connection. It calls the exact same `DbtRunner` used by
`penge-refresh-net-worth` (ADR-0046), takes the same host-mounted `flock`
under `PENGE_REFRESH_STATE_DIR`, and persists the same durable `pending`
marker *before* invoking dbt (mirroring the scheduled worker's own
write-intent tracking), so a killed process or a dbt failure still leaves a
pending refresh for the next scheduled run to retry. The response is
synchronous JSON (`{"status": "succeeded", "completed_at": "<ISO 8601
timestamp>"}`) because a full `dbt build --target refresh` typically
finishes in tens of seconds — there is no job queue or polling endpoint. On
failure the live marts are unchanged and the pending marker is preserved
(or created moments earlier, if none existed) so the next scheduled run
retries — a failed manual trigger never leaves the household with less
retry coverage than not clicking the button at all.

| Status | Meaning                                                              |
| ------ | --------------------------------------------------------------------- |
| `200`  | Shadow build, tests, and promotion succeeded; marker cleared on a best-effort basis (a clear failure is logged but does not turn a success into an error) |
| `503`  | The lock is held by the scheduled worker, a connection sync, or another manual trigger, or the pending marker itself could not be persisted; retry shortly |
| `502`  | The shadow dbt build or promotion failed; live marts are unchanged and the pending marker is preserved (or created moments earlier, if none existed yet) |

## Contract

- Amounts are JSON **strings** (`"1000.0000"`), never floats — they are
  `Decimal` end-to-end and the client converts explicitly.
- EUR and DKK are reported in parallel on every money-bearing row.
- `/accounts.kind` retains the canonical source kind; `reporting_kind`
  supplies the household reporting category. For example,
  `opsparingskonto` remains the Nordnet source kind while mapping to
  `savings` for kind-grouped allocation and historical performance
  (ADR-0048).
- Identifiers are masked server-side; the raw IBAN never leaves the process.
- The OpenAPI schema is committed at [`openapi.json`](openapi.json) and kept
  current by a test; the WebUI's TypeScript client is generated from it.
