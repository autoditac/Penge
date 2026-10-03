# Nordnet (Denmark)

Penge ingests Nordnet (DK) CSV exports: a **transaction** export covering
accounts and a **holdings** export per account per snapshot date. The exports are
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

For staged API imports, upload each file separately and review it before committing.
Import transaction history first; holdings-only uploads resolve instruments from
previously ingested trades or holdings in the same account.
An unmapped holding rejects the entire commit rather than dropping a position.
The CLI can still import a transaction export and holdings files together.

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
| `DEPOTRENTE`               | `cash_interest` (2)           |
| `OVERBELÅNINGSRENTE`       | `cash_interest` (2)           |
| `AFKASTSKAT ASK`           | `tax_ask_charge`              |
| `SKATTEINDBETALING ASK`    | `tax_ask_payment`             |
| *…any other* `…RENTE`      | `cash_interest` (2)           |

(1) For `HÆVNING` and `INDSÆTTELSE` the parser inspects
`Transaktionstekst`; if it matches
`Internal (from\|to) <kontonummer>` the row is reclassified as
`internal_transfer` and the counter-account is preserved on the
parsed record. The loader is then responsible for deduping the
two halves of the transfer (see ADR-0008).

(2) Danish interest types all carry the `RENTE` suffix
(`KREDITRENTE` credit interest, `DEPOTRENTE` custody-account
interest, `OVERBELÅNINGSRENTE` margin/over-collateralization loan
interest, …). They all map to `cash_interest`: the amount's sign
carries the income/expense direction and the row lands in the same
returns and DK `kapitalindkomst` bucket. The well-known types are
listed explicitly above; any other unmapped `…RENTE` type falls
back to `cash_interest` so a new interest label never aborts an
import. See [ADR-0042](../decisions/0042-nordnet-interest-suffix-fallback.md).

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
Holdings-only loads leave transaction-derived cash snapshots untouched.
Only accounts referenced by the upload are upserted; other configured accounts are not changed.
Each Depotoversigt is a **complete security snapshot** for its account/date:
securities held on or before that date but absent from the export receive a
zero-quantity, zero-market-value snapshot on that date, preventing downstream
daily valuation from forward-filling a sold position indefinitely.
Cash is never zeroed this way; it remains derived only from transaction balances.
Reimporting the same account/date replaces omissions in either direction:
previously omitted securities can be restored, and newly omitted ones are zeroed.
An exported header-only holdings file is a valid empty account snapshot and
zeros all previously active securities on that date.
The API accepts it only with the full Nordnet holdings header, no nonblank
data rows, a valid account/date filename, and a configured account; staging
records `empty_snapshot_confirmed: true` and commit rechecks the stored file
against its upload checksum before zeroing positions.
Commit also requires a previously imported, ISIN-mapped security snapshot in
that same Nordnet account on or before the export date. A header-only export
cannot create an account or infer sold holdings from another account.
Excluding **all** rows from a nonempty upload is not equivalent to an empty
export: it is rejected rather than silently liquidating the account.
Do not exclude a valid holding row during review unless you intend to treat that
security as absent from the complete snapshot.
Duplicate account/date files in one CLI load and ambiguous name-to-ISIN mappings
are rejected rather than guessed.

## Staged Imports API

`POST /imports` auto-detects the UTF-16LE `Navn` header as `nordnet_holdings`
(or accepts that explicit `source`).
Keep the Nordnet `Depotoversigt for kontonummer <KONTO>, <D.M.YYYY>.csv`
filename: the account and snapshot date come from it and the account must be
present in `PENGE_NORDNET_ACCOUNTS_CONFIG`.
The response contains one reviewable `holding` row per position; use
`PATCH /imports/{id}/rows/{row_id}` to correct or exclude positions, then
`POST /imports/{id}/commit` to write snapshots.
If a name has no unambiguous account-scoped ISIN mapping, commit returns `409`
without writing anything; import the missing trade history first.
Re-uploading the same account/date is an idempotent snapshot upsert.
See [ADR-0049](../decisions/0049-nordnet-holdings-only-imports.md).

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
