# Nordnet (Denmark)

Penge ingests two Nordnet (DK) CSV exports per import: a
**transaction** export covering every account, and one
**holdings** export per account per snapshot date. The exports are
UTF-16LE BOM tab-separated despite the `.csv` extension.

This connector is **DK-only**. The original German Nordnet
account is closed and out of scope.

## Exporting from Nordnet

In the Nordnet web UI:

1. **Mine konti → Transaktioner** → set the date range (longest
   available is "Hele perioden") → **Eksportér** → save the file
   as `YYYYMMDD-nordnet-transactions-and-notes-export.csv`.
2. **Min portefølje → Beholdninger**, *for each account*, choose
   **Eksportér** → save the file as
   `Depotoversigt for kontonummer <KONTO>, <D.M.YYYY>.csv` (this
   is Nordnet's default; do not rename it — the parser reads the
   account number and snapshot date from the filename).

Drop both files into your import staging directory (location is
deployment-specific; see the loader runbook in a follow-up PR).

## Account-mapping config

Real exports contain account numbers but no owner identity. The
loader looks them up in a YAML file (loaded via
`load_accounts_config()`); the parser itself is account-agnostic
and only consumes the resulting mapping when it needs to
reclassify internal transfers:

```text
config/nordnet-accounts.yaml          # gitignored real config
config/nordnet-accounts.example.yaml  # committed sample
```

Each entry maps a Nordnet kontonummer to the local entity name
and the canonical account kind (`aktiedepot`, `aktiesparekonto`,
`opsparingskonto` — see [ADR-0008](../decisions/0008-nordnet-account-modelling.md)).
Multi-owner setups (e.g. spouse accounts under power-of-attorney)
are supported by simply listing the spouse's accounts under the
spouse's `entity` value.

## Currency handling

DK Nordnet exports populate `Valuta` for the *Beløb* column on
trades and dividends and leave it empty for cash-only rows
(interest, ASK tax, internal transfers). The parser falls back to
`DKK` when the column is empty — every account we operate is
DKK-denominated.

A Valutakonto sub-balance (e.g. an EUR pocket inside a DKK
aktiedepot) is **derived** from the latest transaction `Saldo`
per `(account, currency)` and surfaced as a synthetic
`CASH:<CCY>` instrument snapshot. Nordnet does not export this
sub-balance directly, so this derivation is the only way to
reconcile the running balance — see ADR-0008 for the rationale.

## Transaction-kind mapping

| Nordnet `Transaktionstype` | Canonical `kind`              |
| -------------------------- | ----------------------------- |
| `KØBT`                     | `buy`                         |
| `SOLGT`                    | `sell`                        |
| `UDBYTTE`                  | `dividend`                    |
| `INDBETALING`              | `deposit`                     |
| `HÆVNING`                  | `withdrawal` *or* `internal_transfer` (1) |
| `INDSÆTTELSE`              | `deposit` *or* `internal_transfer` (1) |
| `KREDITRENTE`              | `cash_interest`               |
| `AFKASTSKAT ASK`           | `tax_ask_charge`              |
| `SKATTEINDBETALING ASK`    | `tax_ask_payment`             |

(1) For `HÆVNING` and `INDSÆTTELSE` the parser inspects
`Transaktionstekst`; if it matches
`Internal (from\|to) <kontonummer>` the row is reclassified as
`internal_transfer` and the counter-account is preserved on the
parsed record. The loader is then responsible for deduping the
two halves of the transfer (see ADR-0008).

## Programmatic API

```python
from penge.ingest.nordnet import (
    parse_transactions,
    parse_holdings_file,
    derive_cash_balances,
    instrument_map_from_transactions,
    load_accounts_config,
)

cfg   = load_accounts_config("config/nordnet-accounts.yaml")
txns  = list(parse_transactions("20260507-nordnet-transactions-and-notes-export.csv"))
isin  = instrument_map_from_transactions(txns)        # Navn -> ISIN
cash  = derive_cash_balances(txns)                    # per (account, ccy)
hld   = parse_holdings_file("Depotoversigt for kontonummer 60109543, 7.5.2026.csv")
```

The parser is pure (no DB writes). To upsert into Postgres use
the `penge-nordnet` CLI or the `load_files` API:

```python
from sqlalchemy import create_engine

from penge.ingest.nordnet import load_accounts_config, load_files

engine = create_engine("postgresql+psycopg://...")
result = load_files(
    engine,
    transactions_csv="20260507-nordnet-transactions-and-notes-export.csv",
    holdings_csvs=[
        "Depotoversigt for kontonummer 60109543, 7.5.2026.csv",
        "Depotoversigt for kontonummer 60183456, 7.5.2026.csv",
    ],
    accounts_config=load_accounts_config("config/nordnet-accounts.yaml"),
)
print(result)  # entities=1 accounts=6 instruments=N transactions=N holding_snapshots=N
```

All writes happen in a single transaction and are idempotent —
re-running the same export only updates `updated_at` columns.

## CLI

After `uv sync`:

```sh
uv run --group db penge-nordnet \
    --transactions 20260507-nordnet-transactions-and-notes-export.csv \
    --holdings "Depotoversigt for kontonummer 60109543, 7.5.2026.csv" \
    --holdings "Depotoversigt for kontonummer 60183456, 7.5.2026.csv" \
    --accounts-config config/nordnet-accounts.yaml
```

The CLI reads `DATABASE_URL` (or the assembled `POSTGRES_*` set,
matching `penge-ecb-fx`).

## dbt staging

The staging view `stg_nordnet__transactions` filters
`raw.transaction` to rows whose owning account has
`provider = 'nordnet'`. Marts and tax models should consume that
view — never `raw.transaction` directly — so the
`accepted_values` schema test on `kind` keeps the canonical
vocabulary honest.
