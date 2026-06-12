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

| Field          | Type                                   | Notes                                                    |
| -------------- | -------------------------------------- | -------------------------------------------------------- |
| `date_range`   | `{ from: string; to: string }`         | ISO `YYYY-MM-DD`. `from` must be on or before `to`.      |
| `currency`     | `"EUR" \| "DKK"`                       | Both are first-class; pick whichever the consumer needs. |
| `breakdown_by` | `"none" \| "account" \| "asset_class"` | See semantics below.                                     |

### Output

Array of:

```jsonc
{
  "date": "2024-01-31", // ISO YYYY-MM-DD
  "currency": "EUR", // echoes the request
  "breakdown_key": "brokerage", // omitted when breakdown_by = "none"
  "value": 123456.78, // numeric, summed across the breakdown
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

| Field         | Type                                   | Notes                                                                    |
| ------------- | -------------------------------------- | ------------------------------------------------------------------------ |
| `date_range`  | `{ from: string; to: string }`         | ISO `YYYY-MM-DD`. `from` must be on or before `to`.                      |
| `granularity` | `"day" \| "week" \| "month" \| "year"` | Bucket size. The mart is daily-grain; coarser buckets are summed in SQL. |
| `currency`    | `"EUR" \| "DKK"` (optional)            | Defaults to `EUR`. Both are first-class throughout Penge.                |

### Output

Array of:

```jsonc
{
  "period_start": "2024-01-01", // ISO YYYY-MM-DD, clipped to date_range.from
  "period_end": "2024-01-31", // ISO YYYY-MM-DD, clipped to date_range.to
  "currency": "EUR", // echoes the request (or the default)
  "inflow": 12345.67, // sum of positive cashflows in the bucket
  "outflow": 2345.67, // absolute value of summed negatives
  "net": 10000.0, // inflow - outflow
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
  {
    "period_start": "2024-01-01",
    "period_end": "2024-01-31",
    "currency": "EUR",
    "inflow": 4200.0,
    "outflow": 3100.5,
    "net": 1099.5
  },
  {
    "period_start": "2024-02-01",
    "period_end": "2024-02-29",
    "currency": "EUR",
    "inflow": 4250.0,
    "outflow": 2900.0,
    "net": 1350.0
  },
  {
    "period_start": "2024-03-01",
    "period_end": "2024-03-31",
    "currency": "EUR",
    "inflow": 4300.0,
    "outflow": 3050.0,
    "net": 1250.0
  }
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

| Field           | Type               | Notes                                                            |
| --------------- | ------------------ | ---------------------------------------------------------------- |
| `year`          | `number` (int)     | Tax year; 1900 ≤ year ≤ 2999.                                    |
| `jurisdictions` | `("DK" \| "DE")[]` | Non-empty, unique. One report is produced per requested entry.   |
| `currency`      | `"EUR" \| "DKK"`   | Display currency. Native DK reports are DKK; DE reports are EUR. |

### Output

Array of:

```jsonc
{
  "year": 2024,
  "jurisdiction": "DK", // or "DE"
  "currency": "EUR", // echoes the request
  "summary": {
    // jurisdiction-specific totals (numbers)
    "gross_capital_income": 0.0,
    "taxable_capital_income": 0.0,
    "loss_carry_forward": 0.0,
    "tax_withheld_total": 0.0,
    "prior_loss_carry_forward": 0.0,
  },
  "line_items": [
    { "category": "lager", "amount": 1700.0, "source": "lager:nordnet-1:DK0001234567" },
    { "category": "ask", "amount": 500.0, "source": "ask:ask-1" },
    { "category": "ask_tax_withheld", "amount": 85.0, "source": "ask:ask-1" },
  ],
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

| Category           | Source ID format            | Meaning                                                  |
| ------------------ | --------------------------- | -------------------------------------------------------- |
| `lager`            | `lager:<account>:<isin>`    | DK lagerbeskatning gain/loss per ISIN.                   |
| `ask`              | `ask:<account>`             | DK ASK net taxable gain (17 % settled at source).        |
| `ask_tax_withheld` | `ask:<account>`             | DK ASK 17 % withheld via the account.                    |
| `pal`              | `pal:<account>`             | DK pension return for the year.                          |
| `pal_tax_withheld` | `pal:<account>`             | DK PAL-skat (15.3 %) withheld by the pension provider.   |
| `realised`         | `realised:<acc>:<isin>:<n>` | DK realised gain on a sell event (gennemsnitsmetoden).   |
| `vorabpauschale`   | `de_vorab:<isin>`           | DE deemed annual yield (post-cap, pre-Teilfreistellung). |
| `vorab_taxable`    | `de_vorab:<isin>`           | DE Vorabpauschale × (1 − Teilfreistellung).              |
| `vorab_tax_due`    | `de_vorab:<isin>`           | DE Abgeltungsteuer (26.375 %) on the taxable amount.     |

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

## `run_scenario`

Runs a baseline + scenario Monte-Carlo comparison via the Phase-3
scenario engine (`src/penge/sim/scenario.py`). Returns p10/p50/p90
portfolio paths and a FIRE-year histogram for both the baseline and
the scenario, plus a small `deltas` block (terminal-year p50 EUR
delta and median-FIRE-year shift).

The household baseline (cashflow, tax overlay, FIRE goal, return
model, MC defaults) is loaded from
`${PENGE_SIM_INPUTS_DIR:-data/sim}/baseline.json` — only the scenario
itself and the `monte_carlo` overrides come from the wire. Missing or
malformed baseline JSON is a hard error (no safe empty default).

### Input

| Field           | Type                                             | Notes                                                                                                                                                             |
| --------------- | ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `scenario_type` | `"house_purchase" \| "work_reduction"`           | Discriminator. Determines the shape of `params`.                                                                                                                  |
| `params`        | scenario-specific (see below)                    | Forwarded verbatim to `HousePurchaseScenario` / `WorkReductionScenario` constructors. Strict — extra keys are rejected.                                           |
| `monte_carlo`   | `{ paths: int; seed?: int; horizon_years: int }` | `paths` overrides `mc.n_paths`; `horizon_years` overrides `cashflow.horizon_years`; `seed` (when present) overrides `return_model.seed` for path reproducibility. |

#### `params` for `house_purchase`

| Field             | Type               | Notes                                                 |
| ----------------- | ------------------ | ----------------------------------------------------- |
| `year`            | `int` (2024–2100)  | Calendar year of purchase.                            |
| `price_eur`       | `number \| string` | Full purchase price, EUR. Strings preserve precision. |
| `downpayment_eur` | `number \| string` | Down-payment, EUR. Must be `<= price_eur`.            |
| `mortgage_rate`   | `number \| string` | Annual nominal interest rate in `[0, 1]`.             |
| `term_years`      | `int` (1–50)       | Mortgage term, years.                                 |

#### `params` for `work_reduction`

| Field          | Type               | Notes                                                 |
| -------------- | ------------------ | ----------------------------------------------------- |
| `entity`       | `string`           | Entity identifier in the cashflow projection.         |
| `year`         | `int` (2024–2100)  | First year the reduction takes effect.                |
| `fte_fraction` | `number \| string` | New FTE fraction in `(0, 1]` (e.g. `"0.8"` for 80 %). |

### Output

```jsonc
{
  "baseline": {
    "p10": { "2025": 209028.14, "2026": 218463.81 /* ... */ },
    "p50": {
      /* ... */
    },
    "p90": {
      /* ... */
    },
    "fire_year_distribution": { "2032": 17, "2033": 23 }, // empty when no path met the goal
  },
  "scenario": {
    /* same shape */
  },
  "deltas": {
    "p50_value_eur": -54321.0, // terminal-year p50 delta (scenario - baseline)
    "fire_year_shift_years": 2, // median-FIRE-year shift, or null if undefined
  },
}
```

`p50_value_eur` is the terminal-year (largest year key in
`baseline.p50`) delta of the scenario p50 path versus the baseline p50
path. `fire_year_shift_years` is `scenario.median_fire_year -
baseline.median_fire_year`; either is `null` when the corresponding
median FIRE year is undefined (fewer than 50 % of paths met the goal).

### Example call

```json
{
  "name": "run_scenario",
  "arguments": {
    "scenario_type": "work_reduction",
    "params": { "entity": "person_dk", "year": 2027, "fte_fraction": "0.8" },
    "monte_carlo": { "paths": 1000, "seed": 42, "horizon_years": 25 }
  }
}
```

### Errors

- Invalid input (unknown `scenario_type`, missing required `params`,
  out-of-range `paths` / `horizon_years`, extra keys) →
  `tool/input_invalid`.
- Missing / unparseable
  `${PENGE_SIM_INPUTS_DIR:-data/sim}/baseline.json` →
  `tool/run_scenario_failed`.
- Subprocess failure (Pydantic validation error, scenario produces a
  negative initial portfolio, malformed override) → propagates the
  Python `error: …` message with a non-zero exit code as
  `tool/run_scenario_failed`.

### Audit

Every call is recorded by the MCP audit logger
(`logs/mcp/audit-YYYY-MM-DD.jsonl`) with tool name, redacted arguments,
status, and duration.

## `search_documents`

Search the on-disk document vault by filename, classifier metadata
(year + type) and OCR sidecar text. Returns ranked references —
**never** raw file contents. Excerpts are redacted with the same
value-pattern policy described under "Privacy notes" below.

### Input

| Field   | Type      | Notes                                          |
| ------- | --------- | ---------------------------------------------- |
| `query` | `string`  | Min 2 characters. Matched case-insensitively.  |
| `year`  | `number?` | Optional 4-digit year filter (e.g. `2024`).    |
| `type`  | `string?` | Optional classifier category (see list below). |
| `limit` | `number?` | Defaults to 20. Min 1, max 100.                |

`type` accepts the categories defined in
`src/penge/vault/classifier_rules.yaml`:

`lønseddel`, `gehaltsabrechnung`, `årsopgørelse`, `steuerbescheid`,
`kontoauszug`, `depotauszug`, `pfa-statement`, `hypothek`,
`grundbuch`, `versicherungspolice`, `unsorted`.

### Output

Array of:

```jsonc
{
  "vault_path": "2024/kontoauszug/abcd…-gls-bank-january.pdf", // relative to PENGE_VAULT_ROOT
  "year": 2024, // null when the vault path does not start with a 4-digit year folder
  "type": "kontoauszug",
  "classified_at": "2024-02-02T08:00:00Z", // = vault index `filed_at`
  "hash": "abcd…", // sha256 of the document
  "excerpt": "…Kontoauszug Januar 2024. IBAN: [REDACTED] Saldo am 31.01: …",
  "confidence": 0.4, // search-relevance score in [0, 1]
}
```

Hits are sorted by descending match count, then most-recently-filed,
then `vault_path` for determinism. `confidence` is a saturating
relevance score (`min(1, matches/5)`), not the classifier's own
confidence (which is not persisted in the index today).

### Search strategy

For each entry in `<PENGE_VAULT_ROOT>/.index.json`:

1. Apply optional `year` / `type` filters (derived from the vault path).
2. Count case-insensitive occurrences of `query` in the filename, the
   classifier type, and the OCR sidecar (`<hash>-<slug>.txt` next to the
   document).
3. Drop entries with zero matches; rank the remainder; build a ±50-char
   excerpt around the first OCR match (falling back to the filename).

### Configuration

| Env var            | Default      | Purpose                              |
| ------------------ | ------------ | ------------------------------------ |
| `PENGE_VAULT_ROOT` | `data/vault` | Vault root containing `.index.json`. |

### Privacy notes

- **No file contents are returned.** Only metadata and a short excerpt.
- Excerpts are run through `redactText` before leaving the process.
  IBANs (contiguous and printed 4-char-group form, case-insensitive),
  DK CPR numbers (`\d{6}-?\d{4}`) and long digit runs (`\d{8,}`) —
  typical of account / customer numbers — are replaced with
  `[REDACTED]`.
- The audit logger additionally redacts the `query` argument (and any
  other key whose name matches the standard redaction policy in
  `audit.ts`) before writing the audit record.

### Example call

```json
{
  "name": "search_documents",
  "arguments": { "query": "Kontoauszug", "year": 2024, "limit": 5 }
}
```

### Errors

- Query shorter than 2 chars, unknown `type`, or `limit` out of
  `[1, 100]` → `tool/input_invalid`.
- A missing or unreadable vault index degrades gracefully to an empty
  result array (no error).

### Audit

Every call is recorded by the MCP audit logger
(`logs/mcp/audit-YYYY-MM-DD.jsonl`) with tool name, redacted arguments,
status, and duration.

## `answer_planning_question`

Explanation-first household planning surface for common FIRE-planning questions.
The tool delegates to `penge.sim.planning_surface_cli`, which runs a local
`HouseholdPlan`, readiness report, risk register, and stress-test pack before
returning direct answers linked to evidence, assumptions, risks, limitations, and
documentation.

The current plan id is `synthetic_household`.
It is a fully synthetic DK/DE demo household used for tests and MCP golden evals;
it is not a personal plan and contains no real financial data.

### Input

| Field       | Type                | Notes                                                                 |
| ----------- | ------------------- | --------------------------------------------------------------------- |
| `plan_id`   | `"synthetic_household"` | Optional; defaults to the synthetic household.                     |
| `questions` | `QuestionId[]`      | Optional; defaults to the three core questions below. Unique, max 5. |

Supported `QuestionId` values:

| Question id | Question |
| --- | --- |
| `can_we_retire` | Can this household retire on the planned timeline? |
| `what_breaks_first` | What breaks first if the plan fails? |
| `how_do_taxes_affect_plan` | How do taxes affect this plan? |
| `which_assumptions_matter` | Which assumptions should be reviewed before deciding? |
| `which_scenarios_should_we_test` | Which scenarios should we test before deciding? |

### Output

```jsonc
{
  "plan_id": "synthetic_household",
  "surface": "household_planning_questions",
  "overall_status": "watch",
  "questions": [
    {
      "question_id": "can_we_retire",
      "status": "watch",
      "answer": "The plan is watch for retirement in 2029...",
      "evidence": [{ "label": "planned_retirement_year", "value": "2029", "source": "RetirementReadinessReport" }],
      "risk_codes": ["de_vorabpauschale_not_in_household_plan"],
      "assumption_keys": ["planned_retirement_year", "annual_spending_plan"],
      "limitation_codes": ["planning_grade_not_filing_advice"],
      "docs": ["docs/sim/planning-outputs.md"]
    }
  ],
  "risks": [{ "code": "de_vorabpauschale_not_in_household_plan", "severity": "warning" }],
  "assumptions": [{ "key": "planned_retirement_year", "value": "2029", "source": "HouseholdPlan.members" }],
  "limitations": [{ "code": "planning_grade_not_filing_advice", "docs": ["docs/sim/planning-outputs.md"] }],
  "docs": ["docs/sim/planning-outputs.md", "docs/tax/dk.md", "docs/tax/de.md"]
}
```

The `risk_codes`, `assumption_keys`, and `limitation_codes` fields are deliberate:
LLM hosts should cite them rather than turning the answer into unsupported prose.
The tool returns summaries and references only, not raw documents or raw
transaction/account rows.

## `suggest_import_mapping`

Deterministic, rule-based mapping suggestions for the rows of one
**staged** import session (ADR-0038). This is the sanctioned data path
for AI-assisted categorization in the import wizard: the LLM host calls
this tool instead of ever seeing raw uploads, and the tool itself
contains no LLM — identical inputs always produce identical output.

Suggestions are **pure suggestions**. The tool reads through the same
read-only Postgres pool as every other tool and never writes; accepting
or rejecting a suggestion happens in the import wizard via
`PATCH /imports/{session_id}/rows/{row_id}` (see
[the import sessions API](../api/index.md)).

### Input

| Field               | Type     | Notes                                              |
| ------------------- | -------- | -------------------------------------------------- |
| `import_session_id` | `string` | UUID of a **staged** import session.               |
| `limit`             | `number` | Optional, 1–10000 (default 1000). Max rows read.   |

Sessions that are `committed`, `discarded`, or `expired` are rejected
with an error — suggestions only make sense while a session is still
reviewable. Excluded rows are skipped.

### Output

```jsonc
{
  "session": {
    "id": "0b6c1a52-…",
    "source": "nordnet_transactions",
    "status": "staged",
    "rows_considered": 3
  },
  "suggestions": [
    {
      "row_id": "11111111-…",
      "row_index": 0,
      "kind": "transaction",
      "field": "category", // "category" | "counterparty" | "asset_class"
      "value": "investment.trade.buy",
      "confidence": 0.9, // 0..1, rule strength
      "reason": "canonical nordnet_transactions transaction kind 'buy' maps directly to this category"
    }
  ]
}
```

### Rules and confidence tiers

| Field          | Rule                                                                                                   | Confidence |
| -------------- | ------------------------------------------------------------------------------------------------------ | ---------- |
| `category`     | Canonical transaction kind (`buy`, `dividend`, `internal_transfer`, …) mapped to a fixed category list | 0.9        |
| `category`     | DA/DE/EN keyword match on the row's free text (gebyr/Gebühr, udbytte/Dividende, rente/Zins, …)         | 0.55–0.6   |
| `counterparty` | Instrument name normalized (whitespace collapsed, IBAN/CPR/long-digit-run patterns redacted)          | 0.7        |
| `counterparty` | Free text normalized the same way                                                                      | 0.5        |
| `asset_class`  | `balance` rows → `cash`; `scheme` rows → `pension`                                                     | 0.95       |
| `asset_class`  | Instrument-name keywords (bond/Anleihe/obligation, ETF/UCITS/MSCI, Geldmarkt, gold/Rohstoff)           | 0.65–0.7   |

Rows where no rule fires produce no suggestion — the tool never emits a
low-confidence guess just to fill space.

### Masking

Every suggested `value` and `reason` passes through the same value-
pattern redaction as vault excerpts (`redact.ts`): IBANs, DK CPR
numbers, and long digit runs become `[REDACTED]`. Nordnet free text
like `Internal from 60109543` therefore yields
`Internal from [REDACTED]` as a counterparty suggestion, and values
that are only redaction markers are dropped entirely.

### Example call

```json
{
  "name": "suggest_import_mapping",
  "arguments": { "import_session_id": "0b6c1a52-9d9e-4f7d-8a8e-2f5c6d7e8f90" }
}
```
