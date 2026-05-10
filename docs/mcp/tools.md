# MCP tool reference

Reference for tools exposed by the Penge MCP server (`apps/mcp`). Each
entry describes the tool's purpose, JSON Schema (derived from Zod), and
an example call/response.

The MCP server is **read-only** by construction: every Postgres
connection is forced to `default_transaction_read_only = on`, and tool
output schemas are validated before being returned to the host. Tools
return aggregates only — never raw transactions or account numbers.

## `_meta`

Health-check tool. Returns server identity, the list of registered tool
names, and a UTC timestamp. Useful for clients to verify connectivity
and discover available tools.

## `query_net_worth`

Aggregated daily net worth from the dbt mart `mart_net_worth_daily`.
Returns one row per date (and optional breakdown key) within the
requested date range, valued in the requested currency.

### Input

| Field          | Type                                   | Notes                                                       |
| -------------- | -------------------------------------- | ----------------------------------------------------------- |
| `date_range`   | `{ from: string; to: string }`         | ISO `YYYY-MM-DD`. `from` must be on or before `to`.         |
| `currency`     | `"EUR" \| "DKK"`                       | Both are first-class; pick whichever the consumer needs.    |
| `breakdown_by` | `"none" \| "account" \| "asset_class"` | See semantics below.                                        |

### Output

Array of:

```jsonc
{
  "date": "2024-01-31",         // ISO YYYY-MM-DD
  "currency": "EUR",            // echoes the request
  "breakdown_key": "brokerage", // omitted when breakdown_by = "none"
  "value": 123456.78            // numeric, summed across the breakdown
}
```

### Breakdown semantics

- **`none`** — one row per `as_of`, value summed across all accounts in
  the household.
- **`account`** — one row per (`as_of`, `account_id`).
  `breakdown_key` is the account UUID. The MCP host should not display
  the UUID to the user verbatim — it is opaque, not an account number.
- **`asset_class`** — one row per (`as_of`, `account.kind`).
  `breakdown_key` is the account kind (`bank`, `brokerage`, `pension`,
  `cash`, ...). The mart does not yet carry an instrument-level asset
  class; we map `asset_class ≡ account.kind` from `public.account`.
  When a future mart exposes a true instrument asset class, the wire
  schema will not change.

### Example call

```json
{
  "name": "query_net_worth",
  "arguments": {
    "date_range": { "from": "2024-01-01", "to": "2024-01-03" },
    "currency": "EUR",
    "breakdown_by": "asset_class"
  }
}
```

### Example response

```json
[
  { "date": "2024-01-01", "currency": "EUR", "breakdown_key": "bank", "value": 12000.0 },
  { "date": "2024-01-01", "currency": "EUR", "breakdown_key": "brokerage", "value": 84500.5 },
  { "date": "2024-01-02", "currency": "EUR", "breakdown_key": "bank", "value": 12100.0 },
  { "date": "2024-01-02", "currency": "EUR", "breakdown_key": "brokerage", "value": 85010.2 }
]
```

### Errors

- Invalid input (bad date format, unknown currency, `from > to`,
  unknown `breakdown_by`, extra keys) → `tool/input_invalid`.
- Database errors (e.g. mart not yet built) propagate as the underlying
  Postgres error message.

### Audit

Every call is recorded by the MCP audit logger
(`logs/mcp/audit-YYYY-MM-DD.jsonl`) with tool name, redacted arguments,
status, and duration.

## `query_cashflow`

Aggregated cashflow from the dbt mart `mart_cashflow_daily`, rolled up
to the requested granularity. Returns one row per period within the
requested date range, with summed inflow, outflow, and net cash
movement valued in the requested currency.

### Input

| Field         | Type                                     | Notes                                                                         |
| ------------- | ---------------------------------------- | ----------------------------------------------------------------------------- |
| `date_range`  | `{ from: string; to: string }`           | ISO `YYYY-MM-DD`. `from` must be on or before `to`.                           |
| `granularity` | `"day" \| "week" \| "month" \| "year"`   | Bucket size. The mart is daily-grain; coarser buckets are summed in SQL.      |
| `currency`    | `"EUR" \| "DKK"` (optional)              | Defaults to `EUR`. Both are first-class throughout Penge.                     |

### Output

Array of:

```jsonc
{
  "period_start": "2024-01-01", // ISO YYYY-MM-DD, clipped to date_range.from
  "period_end":   "2024-01-31", // ISO YYYY-MM-DD, clipped to date_range.to
  "currency":     "EUR",        // echoes the request (or the default)
  "inflow":       12345.67,     // sum of positive cashflows in the bucket
  "outflow":       2345.67,     // absolute value of summed negatives
  "net":          10000.00      // inflow - outflow
}
```

### Period semantics

- `period_start` / `period_end` are **inclusive** and **clipped** to the
  requested `date_range`. A `month` bucket containing 2024-01 with
  `date_range.from = 2024-01-15` reports `period_start = 2024-01-15`.
- Days within the range that have no cashflow contribute zero. Buckets
  with no transactions at all are simply absent from the response — the
  consumer should treat absence as zero, not as an error.
- Week boundaries follow Postgres `date_trunc('week', ...)`, i.e.
  ISO weeks starting Monday.

### Example call

```json
{
  "name": "query_cashflow",
  "arguments": {
    "date_range": { "from": "2024-01-01", "to": "2024-03-31" },
    "granularity": "month",
    "currency": "EUR"
  }
}
```

### Example response

```json
[
  { "period_start": "2024-01-01", "period_end": "2024-01-31", "currency": "EUR", "inflow": 4200.0, "outflow": 3100.5, "net": 1099.5 },
  { "period_start": "2024-02-01", "period_end": "2024-02-29", "currency": "EUR", "inflow": 4250.0, "outflow": 2900.0, "net": 1350.0 },
  { "period_start": "2024-03-01", "period_end": "2024-03-31", "currency": "EUR", "inflow": 4300.0, "outflow": 3050.0, "net": 1250.0 }
]
```

### Errors

- Invalid input (bad date format, unknown currency, unknown
  granularity, `from > to`, extra keys) → `tool/input_invalid`.
- Database errors (e.g. mart not yet built) propagate as the underlying
  Postgres error message.

### Audit

Every call is recorded by the MCP audit logger
(`logs/mcp/audit-YYYY-MM-DD.jsonl`) with tool name, redacted arguments,
status, and duration.

## `compute_tax_year`

Computes a per-jurisdiction tax report for a single tax year by
delegating to the Phase-3 Python tax calculators (`penge.tax`). For
**DK** it covers `lagerbeskatning` (mark-to-market on ABIS-listed
funds), `Aktiesparekonto` (flat 17 % wrapper), and `PAL-skat`
(15.3 % yield tax on Danish pension pots). For **DE** it covers
`Vorabpauschale` + `Teilfreistellung` under the InvStG.

The MCP server is TypeScript and the calculators are Python, so the
tool spawns a Python subprocess (`python -m penge.tax …`) and parses
its JSON output. The Python interpreter command is configurable via
`PENGE_PYTHON` (defaults to `python3`); in dev the host typically
launches the server under `uv run` so the working interpreter is the
project's locked uv environment.

### Input

| Field           | Type                  | Notes                                                              |
| --------------- | --------------------- | ------------------------------------------------------------------ |
| `year`          | `number` (int)        | Tax year; 1900 ≤ year ≤ 2999.                                      |
| `jurisdictions` | `("DK" \| "DE")[]`    | Non-empty, unique. One report is produced per requested entry.     |
| `currency`      | `"EUR" \| "DKK"`      | Display currency. Native DK reports are DKK; DE reports are EUR.   |

### Output

Array of:

```jsonc
{
  "year": 2024,
  "jurisdiction": "DK",         // or "DE"
  "currency": "EUR",            // echoes the request
  "summary": {                  // jurisdiction-specific totals (numbers)
    "gross_capital_income": 0.0,
    "taxable_capital_income": 0.0,
    "loss_carry_forward": 0.0,
    "tax_withheld_total": 0.0,
    "prior_loss_carry_forward": 0.0
  },
  "line_items": [
    { "category": "lager", "amount": 1700.0, "source": "lager:nordnet-1:DK0001234567" },
    { "category": "ask",   "amount": 500.0,  "source": "ask:ask-1" },
    { "category": "ask_tax_withheld", "amount": 85.0, "source": "ask:ask-1" }
  ]
}
```

### Inputs file

The CLI reads the household's holdings from
`${PENGE_TAX_INPUTS_DIR:-data/tax}/<year>.json`. If the file does not
exist the report is **empty** (zero totals, zero line items) rather
than an error — this is the expected default before any year has been
populated. The JSON shape is documented in
`src/penge/tax/cli.py`; it accepts
arrays of `LagerInput`, `AskAccount`, `PalInput`, and `VorabInput`
records and an optional `fx` map for cross-jurisdiction currency
conversion.

### Currency conversion

DK calculators are DKK-native; DE calculators are EUR-native. When
`currency` differs from the native currency of a jurisdiction, the
CLI converts amounts using the `fx` map in the inputs file
(e.g. `"fx": {"DKK_to_EUR": "0.134"}`). A missing rate for a
**non-zero** required conversion is a hard error; zero amounts pass
through untouched so an empty report can always render in either
currency.

### Categories

| Category              | Source ID format                | Meaning                                                                |
| --------------------- | ------------------------------- | ---------------------------------------------------------------------- |
| `lager`               | `lager:<account>:<isin>`        | DK lagerbeskatning gain/loss per ISIN.                                 |
| `ask`                 | `ask:<account>`                 | DK ASK net taxable gain (17 % settled at source).                      |
| `ask_tax_withheld`    | `ask:<account>`                 | DK ASK 17 % withheld via the account.                                  |
| `pal`                 | `pal:<account>`                 | DK pension return for the year.                                        |
| `pal_tax_withheld`    | `pal:<account>`                 | DK PAL-skat (15.3 %) withheld by the pension provider.                 |
| `realised`            | `realised:<acc>:<isin>:<n>`     | DK realised gain on a sell event (gennemsnitsmetoden).                 |
| `vorabpauschale`      | `de_vorab:<isin>`               | DE deemed annual yield (post-cap, pre-Teilfreistellung).               |
| `vorab_taxable`       | `de_vorab:<isin>`               | DE Vorabpauschale × (1 − Teilfreistellung).                            |
| `vorab_tax_due`       | `de_vorab:<isin>`               | DE Abgeltungsteuer (26.375 %) on the taxable amount.                   |

### Example call

```json
{
  "name": "compute_tax_year",
  "arguments": {
    "year": 2024,
    "jurisdictions": ["DK", "DE"],
    "currency": "EUR"
  }
}
```

### Errors

- Invalid input (unknown jurisdiction, duplicates, unknown currency,
  out-of-range year, extra keys) → `tool/input_invalid`.
- Subprocess failure (calculator validation error, malformed inputs
  file, missing FX rate for a required conversion) → propagates the
  Python `error: …` message and a non-zero exit code as
  `tool/compute_tax_year_failed`.

### Audit

Every call is recorded by the MCP audit logger
(`logs/mcp/audit-YYYY-MM-DD.jsonl`) with tool name, redacted arguments,
status, and duration. The Python subprocess does not log financial
data to stderr beyond the canonical `error: …` prefix on failure.
