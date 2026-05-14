# Household Planning Snapshot

The **household planning snapshot** (`penge.sim.snapshot`) provides a pure-Python
data model for the household's current financial state, as a seed for running
FIRE simulations.

!!! note "No database connections"
    This module is intentionally side-effect-free.  It works with plain Python
    dicts or dataclass instances provided by the caller — no DB queries, no file
    I/O.  All tests use synthetic fixtures.

---

## Concept

Before a projection can be run, the planner needs a single, validated view of
the household's financial state:

- Which accounts exist (bank, broker, pension…)
- Current balances and currencies
- Which holdings are inside each account
- Cost basis for each holding (needed for accurate bridge-phase tax)
- Any **missing assumptions** that cannot be inferred safely from the raw data

`HouseholdSnapshot` is that view.  It is built by `SnapshotBuilder`, which
accepts one account / holding at a time, validates each entry, and accumulates
all warnings about missing or unsupported data into
`HouseholdSnapshot.missing_assumptions`.

```
SnapshotBuilder("2025-01-15")
  .add_account(...)    # cash, ASK, frie_midler, pension, or manual
  .add_holding(...)    # instrument in an account
  .build()             # → HouseholdSnapshot
```

---

## Account kinds

| Kind           | DK term                           | Tax treatment                               |
|----------------|-----------------------------------|---------------------------------------------|
| `cash`         | Bankkonto / indlånskonto          | Interest taxed as *kapitalindkomst*         |
| `ask`          | Aktiesparekonto                   | Flat **17 %** lager tax                     |
| `frie_midler`  | Frie midler depot                 | Lager (ABIS-listed) or realisationsbeskatning |
| `pension`      | Pensionsdepot (PFA, Nordnet, …)   | *PAL-skat* during accumulation; deferred   |
| `manual`       | Manual / catch-all                | Undefined — human review required          |

The `manual` kind is also used as a **fallback** when the builder encounters an
unrecognised kind string from the database; the warning is recorded in
`missing_assumptions`.

---

## Builder example

```python
from decimal import Decimal
from penge.sim.snapshot import SnapshotBuilder

snapshot = (
    SnapshotBuilder("2025-01-15")
    # Lars — three accounts
    .add_account(
        account_id="lars-gls",
        entity_name="lars",
        account_name="GLS lønkonto",
        kind="cash",
        currency="DKK",
        balance=Decimal("45000"),
        provider="gls",
        data_source="EnableBanking 2025-01-15",
    )
    .add_account(
        account_id="lars-ask",
        entity_name="lars",
        account_name="Nordnet ASK",
        kind="ask",
        currency="DKK",
        balance=Decimal("102000"),
        provider="nordnet",
        data_source="CSV import 2025-01",
    )
    .add_account(
        account_id="lars-pfa",
        entity_name="lars",
        account_name="PFA pension",
        kind="pension",
        currency="DKK",
        balance=Decimal("820000"),
        provider="pfa",
        data_source="PDF import 2025-03",
    )
    # Sofie — two accounts
    .add_account(
        account_id="sofie-lunar",
        entity_name="sofie",
        account_name="Lunar konto",
        kind="cash",
        currency="DKK",
        balance=Decimal("22000"),
        provider="lunar",
        data_source="EnableBanking 2025-01-15",
    )
    .add_account(
        account_id="sofie-fm",
        entity_name="sofie",
        account_name="Nordnet frie midler",
        kind="frie_midler",
        currency="DKK",
        balance=Decimal("315000"),
        provider="nordnet",
        data_source="CSV import 2025-01",
    )
    # Holdings
    .add_holding(
        account_id="lars-ask",
        isin="IE00B4L5Y983",
        instrument_name="iShares Core MSCI World (Acc)",
        quantity=Decimal("34.2"),
        market_value=Decimal("102000"),
        cost_basis=Decimal("88000"),
        currency="DKK",
        data_source="CSV import 2025-01",
    )
    .build()
)

# Inspect
print(snapshot.snapshot_date)               # 2025-01-15
print(snapshot.total_by_kind("cash"))       # {'EUR': Decimal('0'), 'DKK': Decimal('67000')}
print(snapshot.total_by_kind("ask"))        # {'EUR': Decimal('0'), 'DKK': Decimal('102000')}
print(snapshot.missing_assumptions)         # []  — all clean
```

---

## Querying the snapshot

| Method | Description |
|--------|-------------|
| `snapshot.total_by_kind(kind)` | Sum balances for a given kind, split by currency |
| `snapshot.accounts_by_entity(name)` | All accounts owned by an entity |
| `snapshot.holdings_by_account(account_id)` | All holdings in an account |

---

## Missing assumptions

`HouseholdSnapshot.missing_assumptions` is a list of human-readable strings.
An **empty list** means the snapshot is complete and ready to seed a
`HouseholdPlan`.  Non-empty means the planner must resolve the issues before
running a simulation.

### Conditions that trigger a warning

| Trigger | Warning message |
|---------|----------------|
| Unrecognised `kind` | `"account 'id' ('name'): unrecognised kind '…'; cannot determine tax treatment. Set kind to one of […]"` |
| Unsupported `currency` (not EUR or DKK) | `"account 'id' ('name'): unsupported currency '…'; only EUR and DKK are supported"` |
| `cost_basis=None` on a holding | `"holding 'ISIN' in account 'id': cost_basis not available; bridge depletion calculation will be approximate"` |
| Unsupported `currency` on a holding | `"holding 'ISIN' in account 'id': unsupported currency '…'"` |

### How to resolve

1. **Unknown kind** — look up the account in the original data source, determine
   the correct account type, and re-run the builder with the corrected `kind`.
2. **Unsupported currency** — only EUR and DKK are supported in the current
   planning model.  Convert the balance to EUR or DKK at the spot rate and
   record the conversion in `notes`.
3. **Missing cost basis** — check the broker's transaction history export for
   the original purchase price.  If the data is genuinely unavailable, provide
   a conservative estimate and document it in `notes`.

---

## Snapshot provenance

The `data_source` field on every `AccountSnapshot` and `HoldingSnapshot`
records where the data came from and when.  Examples:

- `"EnableBanking 2025-01-15"` — fetched via Enable Banking API on that date
- `"CSV import 2025-03"` — imported from a broker CSV in March 2025
- `"PDF import 2025-03"` — extracted from a pension statement PDF
- `"manual 2025-01-15"` — entered by hand; requires periodic manual refresh

!!! warning "Snapshot staleness"
    A `HouseholdSnapshot` is a point-in-time view.  The `snapshot_date` field
    records the valuation date.  Prices and balances drift over time; rebuild
    the snapshot before each planning run to avoid projecting from stale data.

---

## Limitations

- **Only EUR and DKK** are supported.  Multi-currency households (USD, GBP, SEK,
  …) must convert balances externally before building the snapshot.
- **No live FX conversion** — all balances are stored as-is in their original
  currency; it is the caller's responsibility to handle currency conversion.
- **No real-time pricing** — `market_value` is whatever the data source
  provided; the snapshot does not re-fetch live prices.
- **No DB connection** — the snapshot module itself never opens a database
  connection.  Loading records from Postgres is the caller's responsibility
  (see the monthly ritual runbook).
- **Pension projection parameters** (retirement age, payout period, PAL-skat
  rate) are not stored in the snapshot; they belong to the `CashflowConfig` /
  `PayoutConfig` layer.
