# Skat ABIS list (Aktiebaserede Investeringsselskaber)

The ABIS list is published by Skat (Danish tax authority) and
enumerates the ISINs whose distributions and gains fall under
**lagerbeskatning** (mark-to-market taxation, § 19 LL). Every
December Skat issues an updated CSV covering the rolling
6-year window. Penge keeps a local copy of the list and uses it
to classify each matching instrument as `lagerbeskatning` (when
on the list) or to leave `dk_tax_treatment = NULL` (when off the
list) so the user is forced to review the case manually. The
`realisation` value is only ever written via the manual-override
CLI; the loader never sets it on its own.

This connector is the **only** sanctioned write path for the
`instrument.dk_tax_treatment` column. See ADR-0009 for the
design rationale and ADR-0008 for the account-level treatment
column.

## What it writes

Two operational columns on `instrument`:

- `dk_tax_treatment` — `lagerbeskatning` | `realisation` | `NULL`.
- `dk_tax_treatment_source` — `abis` | `manual` | `NULL`.

The pair is constrained: both NULL or both NOT NULL.

One audit table:

- `instrument_dk_abis_listing(instrument_id, tax_year, listed,
  source_file, imported_at)` — one row per observed
  `(instrument, year)` pair.

## CSV shape

The file Skat ships has these quirks. The parser handles all of
them:

- UTF-8 with BOM, bilingual headers (Danish / English).
- ISIN column may carry trailing whitespace.
- Empty cells are written as `[tom]` (Danish for "empty").
- Year-list columns are usually `,`-separated and quoted, but
  occasionally `.`-separated (without quotes).
- An ISIN may appear in two rows (one per share-class). The
  loader merges them by ISIN and unions the year sets — being
  on the list via *any* share-class is enough.

## Classification rule

For each ISIN matched against the local `instrument` table, the
loader inspects the most recent `tax_year` it observed in the
CSV:

| Latest observation | Resulting `dk_tax_treatment` | `dk_tax_treatment_source` |
|--------------------|------------------------------|----------------------------|
| `listed = true`    | `lagerbeskatning`            | `abis`                     |
| `listed = false`   | `NULL` (forces user review)  | `NULL`                     |

Rows with `dk_tax_treatment_source = 'manual'` are **never**
overwritten; manual decisions are sticky across re-imports.

ISINs in the CSV that are not in the local `instrument` table are
counted as "unmatched" in the `LoadResult` summary; no row is
inserted on their behalf.

## CLI

```sh
just ingest-abis ingest data/abis-listen-2020-2025.csv

# Stick a manual decision (loader will not overwrite this).
just ingest-abis override --isin DE0002635281 --treatment lagerbeskatning

# Drop the manual decision; next ingest will re-derive.
just ingest-abis override --isin DE0002635281 --clear
```

The CLI prints a one-line summary per invocation, e.g.

```text
abis: rows=4774 matched=27 unmatched=4747 obs=162 classified=22 cleared=5
```

`unmatched` is expected to dominate — the ABIS list covers the
universe of Danish-recognised aktiebaserede selskaber, of which
your portfolio holds a small subset.

## Yearly refresh

See [docs/runbook/abis-yearly-refresh.md](../runbook/abis-yearly-refresh.md)
for the runbook.
