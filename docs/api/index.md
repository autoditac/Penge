# Read API

The read API is a small FastAPI application that exposes the analytics marts
to the [modern WebUI](../web/modern-webui.md) as typed JSON.
The reporting endpoints are strictly read-only and local-only; see
[ADR-0035](../decisions/0035-fastapi-read-api.md) for the decision record.
The one sanctioned write surface is the staged import workflow under
`/imports` (see [ADR-0037](../decisions/0037-staged-import-sessions.md)),
which reuses the existing connector parsers and loaders.

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
| `/allocation/current` | Latest-day allocation by `entity`, `currency`, or `kind`         |
| `/accounts`           | Account dimension with IBAN and name suffix masked               |
| `/meta/freshness`     | Latest data date and row count per mart, for staleness banners   |

All series endpoints accept `since`, `until`, `account_id`, `entity_id`,
`limit`, and `offset`; the default window is one year.

## Import sessions

The `/imports` endpoints stage file uploads for review before anything is
written to the warehouse (upload → preview → fix/exclude rows → commit):

| Endpoint                                  | Action                                                        |
| ----------------------------------------- | ------------------------------------------------------------ |
| `POST /imports`                           | Upload a file (multipart); detects the source, stages rows   |
| `GET /imports`                            | List sessions with row counts                                 |
| `GET /imports/{id}`                       | Session detail with paginated staged rows                     |
| `PATCH /imports/{id}/rows/{row_id}`       | Edit a row payload (revalidated) or toggle exclusion          |
| `POST /imports/{id}/commit`               | Write staged rows through the existing connector loaders      |
| `DELETE /imports/{id}`                    | Discard the session and delete the stored upload              |

Supported sources: `nordnet_transactions` (CSV), `growney` (Depotauszug PDF),
`pfa` (Pensionsoversigt PDF), and `manual_balances` (JSON). Nordnet holdings
CSVs are rejected — holdings-only loads silently skip instruments without
transaction history, so they stay on the CLI path for now.

Environment knobs: `PENGE_IMPORT_DIR` (upload storage, default
`data/imports`), `PENGE_IMPORT_MAX_BYTES` (default 25 MiB),
`PENGE_IMPORT_SESSION_TTL_DAYS` (default 7; stale staged sessions expire
lazily), and `PENGE_NORDNET_ACCOUNTS_CONFIG` (accounts YAML required to
commit Nordnet sessions).

## Contract

- Amounts are JSON **strings** (`"1000.0000"`), never floats — they are
  `Decimal` end-to-end and the client converts explicitly.
- EUR and DKK are reported in parallel on every money-bearing row.
- Identifiers are masked server-side; the raw IBAN never leaves the process.
- The OpenAPI schema is committed at [`openapi.json`](openapi.json) and kept
  current by a test; the WebUI's TypeScript client is generated from it.
