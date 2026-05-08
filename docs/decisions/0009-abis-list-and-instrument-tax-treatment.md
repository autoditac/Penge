# 0009 — ABIS list ingestion and `instrument.dk_tax_treatment`

- **Status:** Proposed
- **Date:** 2026-05-08
- **Deciders:** @autoditac
- **Tags:** tax, ingest, data-model

## Context and Problem Statement

Issue #34 calls for parsing Skat's "ABIS list" (the official list of
Danish-recognised *aktiebaserede investeringsselskaber*) and using it
to tag each `instrument` row with its DK tax regime.

Two interlocking decisions are needed:

1. How does an ISIN's presence on the ABIS list map to a Penge
   `dk_tax_treatment` value? Tax law lets a fund move on or off the
   list year-by-year, so the answer is intrinsically per-year.
2. Where does the *current* effective treatment live, given that
   manual overrides must be possible for ambiguous matches (the
   acceptance criterion in #34)?

ADR-0007 fixed the operational schema; `instrument` has no
DK-tax-related columns yet. ADR-0008 added per-account DK tax
treatment for Aktiesparekonto wrappers, but instrument-level
treatment is independent of the account that holds the position.

## Decision Drivers

- **Correctness over cleverness** (repo mindset). A wrong tax flag
  produces a wrong number on a tax filing.
- The tax engine (#36 lagerbeskatning, #35 tax-lot tracking) needs
  to know, for any `(instrument, tax_year)`, whether to apply
  `lagerbeskatning` or `realisation`.
- The user must be able to override an automatic classification —
  e.g. when an ISIN is on the list but has been re-classified for
  the year in question, or when Skat's CSV has an obvious typo.
- The yearly Skat CSV is the **source of truth** but has known
  quirks (`[tom]` placeholders, year separator inconsistency
  `2024,2025` vs `2024.2025`, ~30 duplicate ISINs across
  share-classes per year).
- ADR-0006 mandates ADRs for "tax rule" interpretations.

## Considered Options

### Where to store the treatment

A. **Single `instrument.dk_tax_treatment` column**, derived from the
   most recent ABIS year in the imported CSV. Manual override = directly
   updating the column.
B. **Two columns + per-year audit table**:

- `instrument.dk_tax_treatment` — current effective treatment.
- `instrument.dk_tax_treatment_source` ∈ {`abis`, `manual`} —
  who wrote the value last.
- `instrument_dk_abis_listing(instrument_id, tax_year, listed,
  source_file, imported_at)` — append-only audit of every year
  the ISIN appeared (or did not appear) on a Skat CSV we
  imported.

C. **Per-year column in `instrument` itself** (`dk_2024`, `dk_2025`, …).

### How to interpret the ABIS list

X. **On list → `lagerbeskatning`; off list → `realisation`.** The
   simple rule, matches the existing dk.md placeholder.
Y. **On list → `lagerbeskatning`; off list → leave unset (NULL).**
   Manual review required for non-listed ISINs.
Z. Same as X but per-year.

## Decision

**Option B + Option Y.**

### Schema (Alembic 0003)

`instrument` gains:

| Column                          | Type | Notes                                               |
|---------------------------------|------|-----------------------------------------------------|
| `dk_tax_treatment`              | text | Nullable. CHECK in (`lagerbeskatning`, `realisation`). |
| `dk_tax_treatment_source`       | text | Nullable. CHECK in (`abis`, `manual`). Required iff `dk_tax_treatment` is set. |

A new audit table `instrument_dk_abis_listing` is created with
columns `(id, instrument_id, tax_year, listed, source_file,
imported_at)` and a unique constraint on
`(instrument_id, tax_year)`. The ABIS loader writes one row per
`(ISIN, tax_year)` it sees in the imported CSV. Unmatched ISINs
(not yet in `instrument`) are skipped with a structured warning.

### Interpretation rule (Option Y)

For each `(ISIN, tax_year)` row in a Skat CSV:

- If the year falls in the row's *Registrerede år* set, the
  instrument is **listed** for that year → derived treatment for
  that year is `lagerbeskatning`.
- If the year falls in *Ikke registrerede år*, the instrument is
  **not listed** for that year → derived treatment is **left unset**
  (NULL). The tax engine must surface unclassified instruments to
  the user; it must not silently default to `realisation`.

### Source-precedence rule

`dk_tax_treatment_source = 'manual'` always wins. The ABIS loader
**only updates** rows where `dk_tax_treatment_source` is `NULL` or
`'abis'`. Manual overrides are sticky across re-imports.

The current effective treatment (`instrument.dk_tax_treatment`) is
derived from the *most recent* ABIS year for which we have a
listing row. When a fund is delisted in year *N+1*, the next ABIS
import will record `listed=false` for year *N+1* and clear
`dk_tax_treatment` (set to NULL) on instruments whose source is
`abis`, prompting a manual review. Historical years remain in the
audit table for the tax engine to reason per-year about open lots.

### Manual override mechanism

The CLI `penge-abis override --isin <ISIN> --treatment <X>` (and a
matching `--clear` flag) writes the column directly with
`dk_tax_treatment_source='manual'`. Subsequent ABIS imports leave
the row alone. There is no separate override table; the source flag
on the column is the single point of truth. This is simpler than a
join and matches the per-account `dk_tax_treatment` modelling from
ADR-0008.

## Consequences

### Positive

- The audit table `instrument_dk_abis_listing` lets the tax engine
  answer per-year questions ("was this fund on the list in 2022?")
  without re-parsing the CSV.
- A user-set override is never silently overwritten by an automated
  yearly refresh.
- Schema only grows by two scalar columns + one append-only table;
  existing reads (e.g. net-worth marts) are unaffected.
- The "leave NULL when delisted" rule forces the user to think about
  reclassifications instead of a silent regime change.

### Negative

- The two-column representation (treatment + source) is mildly
  redundant with the audit table, which also encodes the per-year
  truth. We accept the redundancy because reads of "what's the
  current treatment of this ISIN?" must be one-row, no-join, fast.
- The `dk_tax_treatment` enum is initially binary
  (`lagerbeskatning`, `realisation`). Aktiesparekonto already lives
  on `account.dk_tax_treatment` from ADR-0008 and is not duplicated
  here. PFA / pension-style PAL-skat instruments will need a future
  migration to extend the enum.

### Neutral

- The CSV is downloaded yearly from skat.dk and stored under
  `data/sources/abis/` (gitignored). The runbook documents the
  fetch + ingest steps. No automatic web-scrape; correctness > speed.

## Alternatives in detail

### Option A — single column, no audit

Rejected: loses per-year history needed by tax-lot accounting (#35)
when a fund changes regime mid-life.

### Option C — per-year columns

Rejected: schema grows yearly; UI joins multiply; no advantage over
the audit table.

### Option X — off-list defaults to `realisation`

Rejected: the ABIS list does not enumerate every fund a Danish
investor might hold. A non-Danish or recently-launched ETF may be
absent from the list because it has never been classified, *not*
because it is realisation-taxed. Defaulting to `realisation` would
silently apply the wrong rule. The decision criteria in this repo
say "do not silently change a tax rule"; the conservative choice is
to leave NULL and require a human decision.

## Links

- ADR-0006 — Trunk-based + Conventional Commits + ADRs
- ADR-0007 — Initial relational data model
- ADR-0008 — Account modelling (DK ASK)
- Issue #34 — ABIS list ingestion
- Issue #35 — Tax-lot tracking
- Issue #36 — DK Lagerbeskatning calculator
- [`docs/connectors/abis.md`](../connectors/abis.md)
- [`docs/runbook/abis-yearly-refresh.md`](../runbook/abis-yearly-refresh.md)
