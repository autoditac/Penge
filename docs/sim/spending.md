# Household Spending & Target-Expense Model

The spending model lets you declare what a household *needs* to spend each year
across the three FIRE lifecycle phases, so that FIRE readiness is assessed
against household needs rather than only asset balances.

---

## Concepts

### Spending phases

| Phase | Description |
|---|---|
| `accumulation` | Working years; salary income covers expenses. |
| `bridge` | Post-employment, pre-pension; portfolio drawdown or part-time income fills the gap. |
| `retirement` | Full pension income phase. |

### Recurring rules (`SpendingRule`)

A `SpendingRule` describes an annual outgoing that may be:

- **time-bounded** — active only between `active_from` and `active_until` (both inclusive, both optional).
- **phase-specific** — applies only to one lifecycle phase; `phase=None` means all phases.
- **inflation-indexed** — the base-year amount is compounded by `inflation_rate` (per-rule; default 2 %) for each year since the base year.

### One-off expenses (`OneOffExpense`)

A single expense that occurs in exactly one calendar year (e.g. a kitchen
renovation or a car purchase).  One-off amounts are added to the recurring
total for that year only.

### Currency isolation

All amounts stay in their declared currency (`"EUR"` or `"DKK"`).
`compute_spending()` returns a dict with **separate** `"EUR"` and `"DKK"` keys.
**No implicit currency conversion is performed.**  Callers that need a
consolidated figure must apply an FX rate explicitly.

---

## Inflation indexing

For a recurring rule, the effective amount in a given year is:

```text
effective_amount = annual_amount × (1 + inflation_rate) ^ (year − base_year)
```

The `base_year` is resolved in this priority order:

1. `inflation_base_year` on the rule (explicit override).
2. `active_from` on the rule (rule start year).
3. The target `year` itself — meaning **no compounding** when neither bound is
   known.

This means inflation is **per-rule**; there is no global inflation override.
Different spending categories can carry different inflation rates (e.g. housing
CPI vs. healthcare CPI).

### Example

```python
from decimal import Decimal
from penge.sim.spending import SpendingRule, SpendingPhase

# Rent inflates at 3 % per year from 2025
rent = SpendingRule(
    label="rent",
    annual_amount=Decimal("12000"),
    currency="EUR",
    active_from=2025,
    inflation_rate=Decimal("0.03"),
)
# In 2030: 12 000 × 1.03^5 = 13 927.68 EUR
```

---

## API reference

### `SpendingPhase`

```python
class SpendingPhase(str, Enum):
    ACCUMULATION = "accumulation"
    BRIDGE = "bridge"
    RETIREMENT = "retirement"
```

### `SpendingRule`

| Field | Type | Default | Description |
|---|---|---|---|
| `label` | `str` | — | Human-readable name |
| `annual_amount` | `Decimal` | — | Base-year annual spending (must be > 0) |
| `currency` | `"EUR" \| "DKK"` | — | Source currency |
| `phase` | `SpendingPhase \| None` | `None` | Phase filter; `None` = all phases |
| `active_from` | `int \| None` | `None` | First active year (inclusive) |
| `active_until` | `int \| None` | `None` | Last active year (inclusive) |
| `inflation_rate` | `Decimal` | `0.02` | Per-rule annual inflation rate |
| `inflation_base_year` | `int \| None` | `None` | Explicit inflation base year |

### `OneOffExpense`

| Field | Type | Description |
|---|---|---|
| `label` | `str` | Human-readable name |
| `year` | `int` | Calendar year the expense occurs |
| `amount` | `Decimal` | Positive monetary amount |
| `currency` | `"EUR" \| "DKK"` | Source currency |

### `HouseholdSpendingPlan`

```python
@dataclass
class HouseholdSpendingPlan:
    rules: list[SpendingRule] = field(default_factory=list)
    one_offs: list[OneOffExpense] = field(default_factory=list)
```

### `compute_spending`

```python
def compute_spending(
    plan: HouseholdSpendingPlan,
    year: int,
    phase: SpendingPhase,
) -> dict[Literal["EUR", "DKK"], Decimal]:
    ...
```

Returns `{"EUR": <total>, "DKK": <total>}` — always both keys, zero if
nothing applies.

---

## Full FIRE scenario example

```python
from decimal import Decimal
from penge.sim.spending import (
    HouseholdSpendingPlan,
    OneOffExpense,
    SpendingPhase,
    SpendingRule,
    compute_spending,
)

plan = HouseholdSpendingPlan(
    rules=[
        # Base living costs — all phases, CPI-indexed from 2025
        SpendingRule(
            label="living_costs",
            annual_amount=Decimal("36000"),
            currency="EUR",
            active_from=2025,
            inflation_rate=Decimal("0.02"),
        ),
        # Commuting costs — accumulation phase only
        SpendingRule(
            label="commuting",
            annual_amount=Decimal("3600"),
            currency="EUR",
            phase=SpendingPhase.ACCUMULATION,
            active_from=2025,
            inflation_rate=Decimal("0.02"),
        ),
        # Danish pension supplementary costs in DKK — bridge phase
        SpendingRule(
            label="dk_bridge_costs",
            annual_amount=Decimal("60000"),
            currency="DKK",
            phase=SpendingPhase.BRIDGE,
            active_from=2042,
            active_until=2051,
            inflation_rate=Decimal("0.025"),
        ),
    ],
    one_offs=[
        # Kitchen renovation in 2028
        OneOffExpense(
            label="kitchen_renovation",
            year=2028,
            amount=Decimal("20000"),
            currency="EUR",
        ),
    ],
)

# Accumulation year 2030
acc = compute_spending(plan, 2030, SpendingPhase.ACCUMULATION)
print(acc)  # {'EUR': ..., 'DKK': Decimal('0.00')}

# Bridge year 2045
brg = compute_spending(plan, 2045, SpendingPhase.BRIDGE)
print(brg)  # {'EUR': ..., 'DKK': ...}
```

---

## Assumptions and limitations

1. **No global inflation override.** Each rule carries its own `inflation_rate`.
   If you want a unified CPI across all rules, set the same `inflation_rate`
   on every rule (or derive them from a shared constant).

2. **No implicit FX conversion.** EUR and DKK buckets are always separate.
   Bridge/retirement readiness calculations must apply an explicit FX rate if
   a single consolidated figure is required.

3. **Annual granularity.** Spending is modelled yearly.  Within-year
   timing (e.g. a mid-year redundancy payment) is not captured.

4. **No dependency on salary or portfolio.** The spending model is
   intentionally decoupled from the cashflow engine.  Use the output of
   `compute_spending()` as an input constraint to your FIRE readiness
   calculation.

5. **One-off expenses are not inflation-adjusted.** They are expressed in
   nominal terms for the year in which they occur.

6. **Negative spending is not supported.** All `annual_amount` and `amount`
   values must be strictly positive.  Model income as a negative-spending
   offset via the cashflow engine, not here.
