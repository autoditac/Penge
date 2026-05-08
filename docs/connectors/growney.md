# Growney / Sutor Bank Depotauszug

Provider slug: `growney`.
Account kind: `aktiedepot` (German Wertpapierdepot).
Account currency: `EUR`.
Source format: **PDF** (Depotauszug emitted by Sutor Bank).

> Issue [#19](https://github.com/autoditac/Penge/issues/19) originally
> requested a "Growney CSV parser". Growney itself does not export
> portfolio data; the regulated custodian behind every Growney
> account is **Sutor Bank**, which mails a quarterly **Depotauszug**
> PDF and does not provide a CSV alternative. The connector therefore
> parses Sutor's PDF rather than a non-existent CSV.

## What gets ingested

| Sutor section | Penge target |
|---|---|
| `Aufstellung über Kundenfinanzinstrumente per …` (holdings table) | `holding_snapshot` rows |
| `Geldsaldo` line | one synthetic `CASH:EUR` `holding_snapshot` row (only when non-zero) |
| `Umsätze vom … bis … in EUR` (transactions table) | `transaction` rows |
| Header line `"<strategy>" Nr. <depot> / IBAN: <iban>` | `account` row (one per depot) |

The header line is parsed by `DEPOT_HEADER_RE` and the per-quarter window
by `PERIOD_RE` in `penge.ingest.growney.constants`.

## Transaction kind mapping

Sutor's `Transaktion` column is mapped to the canonical Penge
vocabulary:

| Sutor | Penge `transaction.kind` |
|---|---|
| `Einzahlung` | `deposit` |
| `Auszahlung` | `withdrawal` |
| `Kauf` | `buy` |
| `Verkauf` | `sell` |
| `Ausschüttung` | `dividend` |
| `Gebühr` | `fee` |

`Betrag (netto)` is used as the signed amount: outflows (Kauf,
Gebühr, Auszahlung) are negative, inflows (Einzahlung,
Ausschüttung) are positive.

## Currency handling

All money columns (Brutto, Netto, Kosten, KESt+SolZ, KiSt) are in
EUR. The unit price column (`Anteile / Gramm` ↔ `Kurs / Preis`)
may be in USD; in that case Sutor reports the EUR/USD FX rate in
the `W-Kurs` column. The connector stores:

- `transaction.amount` — net EUR (signed),
- `transaction.price` — unit price in its native currency,
- `transaction.fx_rate` — EUR per foreign-currency unit (only set
  for foreign-priced rows).

Holdings are stored with `market_value_eur` always in EUR even
when the row's price column is in USD.

## Stable transaction id

Sutor's PDF does not assign a transaction id, and the same
boundary row appears on two adjacent quarterly statements. To
make ingest idempotent the loader synthesises a stable id by
hashing `(depot_number, bookkeeping_date, value_date, sutor_type,
isin, quantity, net_amount_eur, description)` with sha256 and
prefixing the first 16 hex chars with `growney:`. See
`synthesize_external_id` in `penge.ingest.growney.parser`.

## CLI

```bash
just ingest-growney --entity-name "Your Name" \
    ~/Nextcloud/Documents/Sutor/2026Q1.pdf \
    ~/Nextcloud/Documents/Sutor/2026Q2.pdf
```

Or directly:

```bash
uv run --group db --group http --group parsers \
    penge-growney --entity-name "Your Name" path/to/depot.pdf
```

The CLI reads `DATABASE_URL` (or the assembled `POSTGRES_*`
fallback) just like the Nordnet and Lunar CLIs.

## Re-running

The loader is idempotent: re-ingesting the same PDF (or the next
quarter's PDF, which restates the previous quarter's last row) is
a no-op except for refreshing `holding_snapshot.market_value` for
the most recent `as_of`. The synthesised `external_id` makes the
upsert keys stable across re-runs.

## Limitations

- The connector parses German-locale PDFs only; the column order
  is positional.
- Sutor uses `Anteile` for ETF units; other unit labels (e.g.
  `Gramm` for precious metals) round-trip through the `unit`
  field but are not currently mapped to a separate instrument
  kind.
- Cost basis is not on the Depotauszug; `holding_snapshot.cost_basis`
  is left `NULL` for security positions.
