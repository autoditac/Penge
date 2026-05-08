# 0008 — Nordnet account modelling: kind vocabulary, multi-currency cash, ASK tax shell

- **Status:** Accepted
- **Date:** 2026-05-07
- **Deciders:** @autoditac
- **Tags:** ingest, data-model, tax

## Context and Problem Statement

Nordnet is the first broker connector (issue #17) and exposes three
distinct *account kinds* with materially different tax and reporting
semantics:

- **AKT** — *Aktiedepot*: a regular taxable securities depot.
  Realisation-method capital-gains tax (Danish
  `realisationsbeskatning`).
- **ASK** — *Aktiesparekonto*: a Danish capital-tax-advantaged shell
  with an annual flat rate (currently 17 %) computed on the
  inventory-method (`lagerbeskatning`). Nordnet emits two synthetic
  transaction kinds inside the wrapper: `AFKASTSKAT ASK` (tax
  withheld) and `SKATTEINDBETALING ASK` (tax payment).
- **OPS** — *Opsparingskonto*: a pure interest-bearing cash account
  with no securities; only `INDBETALING` / `HÆVNING` / `KREDITRENTE`
  rows.

In addition, AKT depots can hold non-DKK securities and Nordnet
tracks the matching foreign cash float as a *Valutakonto*
sub-balance (e.g. `60183456` has a EUR Valutakonto). The
Valutakonto is **not** a separate account number — it is a
sub-balance of the parent AKT account — and Nordnet does **not**
expose it as a downloadable CSV. The only signal of its current
balance is the `Saldo` column on the most recent transaction in
that currency in the parent account's transaction CSV.

ADR-0007 fixed the operational schema with a free-text
`account.kind` column. This ADR locks in the *vocabulary* and
*modelling rules* for that column and for cash sub-balances and
ASK tax events, so that Nordnet (#17), GoCardless (#13), and the
analytics marts (#24) all interpret the same data identically.

## Decision Drivers

- ADR-0003 commits us to hybrid ingestion: CSV is authoritative for
  Nordnet because its PSD2 surface is read-only-of-cash and lacks
  positions and tax events.
- ADR-0004 requires EUR and DKK shown in parallel, so foreign-cash
  positions must be first-class, not hidden inside the AKT total.
- ADR-0007 already provides `account.kind` (Text) and the
  `holding_snapshot` table; we want to add semantics, not migrate.
- The Aktiesparekonto's annual lagerbeskatning is a closed-form
  computation, but auditing it requires the per-year Nordnet-issued
  `AFKASTSKAT ASK` and `SKATTEINDBETALING ASK` rows to remain
  individually addressable.
- Multi-owner: PoA accounts (Monika, Carlotta) sit under separate
  `entity` rows, so account modelling must work with the existing
  `account.entity_id` FK without per-owner branching.

## Considered Options

1. **One `account` row per (Nordnet account, currency)** — model
   each Valutakonto as its own `account` row with a synthetic
   external id like `60183456:EUR`.
2. **One `account` row per Nordnet account; cash held as
   `holding_snapshot` rows against a synthetic `CASH:<CCY>`
   instrument.**
3. **One `account` row per Nordnet account; foreign cash held as
   a sibling row in a new `cash_balance` table** keyed on
   `(account_id, currency, as_of)`.

For ASK tax events we considered: (a) collapse them into the
existing `transaction.kind = 'tax'` bucket, or (b) preserve them as
distinct `tax_ask_charge` and `tax_ask_payment` kind values.

## Decision

### Account kind vocabulary

`account.kind` for Nordnet rows takes one of three values:

| Value             | Nordnet badge | Semantics                                         |
|-------------------|---------------|---------------------------------------------------|
| `aktiedepot`      | AKT           | Taxable securities depot, realisation method.     |
| `aktiesparekonto` | ASK           | DK capital-tax wrapper, lagerbeskatning.          |
| `opsparingskonto` | OPS           | Pure cash savings, interest only.                 |

These string constants are exported from
`penge.ingest.nordnet` as a frozen module-level mapping so dbt
staging models, Streamlit, and the tax modules import the same
literals.

### Multi-currency cash: chosen Option 2

We model **one `account` row per Nordnet account number**. Cash —
in *any* currency, including the AKT account's own basisvaluta —
is recorded as `holding_snapshot` rows against synthetic
`instrument` rows with `kind = 'cash'`, `isin = NULL`,
`ticker = 'CASH:<CCY>'`, `currency = <CCY>`. One synthetic
instrument exists per ISO-4217 currency we ever encounter
(e.g. `CASH:DKK`, `CASH:EUR`, `CASH:USD`).

Rationale:

- Keeps the canonical "what does Rouven hold" query a single union
  of `holding_snapshot`, with cash and securities side by side.
- Avoids a new table (Option 3) and the migration cost.
- Avoids fake account numbers (Option 1) and the artificial
  parent/child relationship we would have to invent to keep PSD2
  reconciliation working against the *real* account number.
- `account.currency` retains its meaning as the *basisvaluta* (the
  currency Nordnet denominates the account in for statements);
  per-currency cash is a property of holdings, not of the account.

### Cash sub-balance derivation

Because Nordnet does not export the Valutakonto, the most recent
non-DKK `Saldo` per `(account, currency)` from the transaction CSV
is the authoritative source. The Nordnet loader emits one
`holding_snapshot` row per `(account_id, CASH:<CCY>, as_of_date)`
where `as_of_date` is the value date of that latest transaction,
`quantity == latest Saldo`, and `market_value == latest Saldo`
(price = 1 in the cash currency). The basisvaluta cash position
is derived from the same column with no special-casing.

### ASK tax event preservation

We preserve the two ASK tax kinds as distinct
`transaction.kind` values rather than collapsing into `tax`:

- `tax_ask_charge` — Nordnet `AFKASTSKAT ASK` rows.
- `tax_ask_payment` — Nordnet `SKATTEINDBETALING ASK` rows.

This keeps the lagerbeskatning audit trail addressable per year
without re-parsing `Transaktionstekst`. The general realisation
method on AKT depots continues to use the existing tax fields on
the trade transaction itself.

### Internal-transfer dedup

`INDSÆTTELSE` / `HÆVNING` rows whose `Transaktionstekst` matches
`Internal (from|to) (\d+)` carry the counter-account in a
parser-level field; the loader stamps them with
`transaction.kind = 'internal_transfer'` so the net-worth mart
(#24) can drop both legs from inflow/outflow aggregates without
losing the audit trail.

## Consequences

### Positive

- One uniform "holdings" surface for cash and securities.
- ASK tax events remain individually queryable for audits and
  for reconciling against SKAT's annual statement.
- No schema migration needed — vocabulary lives in code, and
  CASH instruments are inserted on demand by the loader.
- The model extends naturally to GoCardless (kind `bank`,
  `credit_card`) and to manual-entry pension accounts.

### Negative

- Cash quantities are stored in `holding_snapshot.quantity`
  (`Numeric(28, 8)`) rather than in a money column
  (`Numeric(20, 4)`). The chosen type has more decimal places
  than needed for cash, but reusing the existing column avoids a
  schema migration and keeps the holdings union uniform.
- The synthetic `CASH:<CCY>` rows in `instrument` are not real
  tradable assets; downstream views must filter them out where a
  "tradable instrument" sense is meant. Mitigation: dbt staging
  model exposes `is_cash` boolean.
- Cash positions are only as fresh as the latest transaction;
  an account with no movement in a quarter looks stale. Mitigation:
  the dashboard surfaces `as_of_date` next to each cash balance.

### Neutral

- ASK lagerbeskatning computation remains a future concern (#36);
  this ADR only ensures the data is captured losslessly.
- `account.kind` remains free-text in the schema; enforcement of
  the vocabulary is loader-side, not constraint-side. A future
  migration may add a `CHECK` constraint once all connectors are
  in.

## Alternatives in detail

### Option 1 — separate `account` row per currency

Rejected. Creates fictitious account numbers, breaks PSD2
reconciliation against Nordnet's real account ids, and forces a
parent/child relationship into a schema that does not have one.
Also makes "list my Nordnet accounts" a confusing query.

### Option 3 — dedicated `cash_balance` table

Rejected for now. Adds a table and a migration, splits the
"what do I own" query into two unions, and offers no benefit over
synthetic instruments other than mild aesthetic cleanliness.
Reconsider if cash modelling grows features (interest accrual,
sweep accounts, money-market funds) that securities don't share.

## Links

- ADR-0003 — Hybrid ingestion (PSD2 + CSV/PDF)
- ADR-0004 — EUR and DKK shown in parallel
- ADR-0007 — Initial relational data model
- Issue #17 — Nordnet CSV parser
- Issue #24 — `mart_net_worth_daily`
- Issue #36 — DK Lagerbeskatning calculator
- [`docs/connectors/nordnet.md`](../connectors/nordnet.md) —
  column-level CSV schema and parser behaviour
