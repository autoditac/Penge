# Read API

The read API is a small FastAPI application that exposes the analytics marts
to the [modern WebUI](../web/modern-webui.md) as typed JSON.
It is strictly read-only and local-only; see
[ADR-0035](../decisions/0035-fastapi-read-api.md) for the decision record.

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

## Contract

- Amounts are JSON **strings** (`"1000.0000"`), never floats — they are
  `Decimal` end-to-end and the client converts explicitly.
- EUR and DKK are reported in parallel on every money-bearing row.
- Identifiers are masked server-side; the raw IBAN never leaves the process.
- The OpenAPI schema is committed at [`openapi.json`](openapi.json) and kept
  current by a test; the WebUI's TypeScript client is generated from it.
