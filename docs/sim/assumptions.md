# Investment assumption catalog

> Module: `penge.sim.assumptions` — issue #177

The assumption catalog is a lightweight typed registry that stores
per-instrument or per-account assumptions needed by the household planner and
liquid-depot simulation.  Externalising these values into a catalog has three
benefits:

1. **No hidden drivers** — expense ratios, dividend yields, and FX costs
   are explicit and reviewable instead of scattered as magic numbers across
   projection scripts.
2. **Single source of truth** — a scenario that references an instrument
   retrieves its assumptions from the catalog; updating the catalog
   propagates the change to all scenarios automatically.
3. **Early validation** — `AssumptionCatalog.validate()` surfaces suspicious
   or incomplete entries *before* a projection is run, not after.

---

## Tax regimes

| Enum value              | String value    | Description                                                                 |
|-------------------------|-----------------|-----------------------------------------------------------------------------|
| `TaxRegime.LAGER`       | `"lager"`       | Mark-to-market annual tax (lagerbeskatning). Annual gains taxed at 27/42 %. |
| `TaxRegime.REALISATION` | `"realisation"` | Deferred capital-gain tax. Dividends taxed annually; gains on sale.         |
| `TaxRegime.ASK`         | `"ask"`         | Aktiesparekonto flat 17 % lager tax.                                        |

---

## `InstrumentAssumptions` fields

| Field            | Type                      | Default        | Description                                                                                             |
|------------------|---------------------------|----------------|---------------------------------------------------------------------------------------------------------|
| `isin`           | `str`                     | *(required)*   | ISIN or other unique identifier.                                                                        |
| `label`          | `str`                     | *(required)*   | Human-readable name (e.g. ticker + share class).                                                        |
| `currency`       | `"EUR"` or `"DKK"`        | *(required)*   | The instrument's native trading currency.  Not the projection currency.                                 |
| `tax_regime`     | `TaxRegime`               | *(required)*   | Tax regime that governs gains in this instrument.                                                       |
| `expense_ratio`  | `Decimal`                 | *(required)*   | Annual total expense ratio (ÅOP) as a decimal fraction. `Decimal("0.002")` = 0.20 %.                   |
| `dividend_yield` | `Decimal`                 | `Decimal("0")` | Expected annual dividend yield as a decimal fraction in `[0, 1]`. `Decimal("0.015")` = 1.5 %.         |
| `ask_eligible`   | `bool`                    | `False`        | Whether the instrument is eligible for deposit into an ASK account.                                     |
| `fx_cost`        | `Decimal`                 | `Decimal("0")` | One-way FX conversion cost per trade as a decimal fraction. `Decimal("0.0025")` = 0.25 %.              |
| `notes`          | `str`                     | `""`           | Free-text explanation for non-obvious choices or manual overrides.                                      |

!!! note "Rates are annual decimals"
    Both `expense_ratio` and `dividend_yield` are **annual** values expressed
    as decimal fractions, not percentages.  `Decimal("0.002")` means 0.20 %
    per year.

!!! note "`currency` is the instrument's native currency"
    The `currency` field records the currency in which the instrument itself
    is denominated (e.g. `"EUR"` for a Dublin-domiciled UCITS ETF), not the
    currency of the projection.  The projection engine holds its own FX
    conversion rate.

---

## `AssumptionCatalog` methods

| Method                     | Returns                            | Description                                                              |
|----------------------------|------------------------------------|--------------------------------------------------------------------------|
| `add(assumptions)`         | `None`                             | Register (or overwrite) an entry. Logs a debug message on overwrite.     |
| `get(isin)`                | `InstrumentAssumptions`            | Retrieve by ISIN. Raises `KeyError` if not found.                        |
| `get_or_none(isin)`        | `InstrumentAssumptions \| None`    | Retrieve by ISIN, or `None` if not found.                                |
| `all()`                    | `list[InstrumentAssumptions]`      | All entries in insertion order.                                          |
| `validate()`               | `list[str]`                        | Warning strings for suspicious entries. Empty list = clean catalog.      |

---

## Validation checks

`validate()` returns a list of human-readable warning strings.  An empty
list means the catalog looks clean.  The following checks are performed:

* **`ask_eligible=True` with non-ASK tax regime** — an ASK-eligible
  instrument held *inside* an ASK account should be catalogued with
  `tax_regime=TaxRegime.ASK`.  Mixing flags is likely a copy-paste error.
* **High dividend yield on Realisation instrument** — a `dividend_yield`
  above 10 % on a `TaxRegime.REALISATION` instrument is unusual and worth
  double-checking against the fund factsheet.
* **`fx_cost > 0` on a DKK instrument** — DKK-denominated instruments do
  not normally incur FX conversion costs.  A non-zero value should be
  accompanied by an explanation in `notes`.

---

## How to maintain the catalog

### Adding a new instrument

```python
from decimal import Decimal
from penge.sim.assumptions import AssumptionCatalog, InstrumentAssumptions, TaxRegime

catalog = AssumptionCatalog()

catalog.add(InstrumentAssumptions(
    isin="IE00B4L5Y983",
    label="iShares Core MSCI World UCITS ETF (Acc)",
    currency="EUR",
    tax_regime=TaxRegime.LAGER,       # ABIS-listed → lagerbeskatning
    expense_ratio=Decimal("0.002"),    # 0.20 % ÅOP
    dividend_yield=Decimal("0"),       # accumulation class
    ask_eligible=False,
    fx_cost=Decimal("0.0025"),         # Nordnet 0.25 % FX spread
    notes="ABIS list 2024; TER from KIID 2024-01-15",
))
```

### Adding an ASK-eligible instrument

```python
catalog.add(InstrumentAssumptions(
    isin="DK0060950053",
    label="Example ASK-eligible fund",
    currency="DKK",
    tax_regime=TaxRegime.ASK,
    expense_ratio=Decimal("0.005"),
    dividend_yield=Decimal("0"),
    ask_eligible=True,
    fx_cost=Decimal("0"),
))
```

### Correcting an assumption (override)

Adding an entry for an ISIN that is already in the catalog silently replaces
the old entry.  Document the reason in `notes`:

```python
catalog.add(InstrumentAssumptions(
    isin="IE00B4L5Y983",
    label="iShares Core MSCI World UCITS ETF (Acc)",
    currency="EUR",
    tax_regime=TaxRegime.LAGER,
    expense_ratio=Decimal("0.0015"),   # corrected: TER reduced from 0.20 % to 0.15 %
    dividend_yield=Decimal("0"),
    ask_eligible=False,
    fx_cost=Decimal("0.0025"),
    notes="override: new TER confirmed in fund factsheet 2025-03-01",
))
```

### Running validation before a projection

```python
warnings = catalog.validate()
if warnings:
    for w in warnings:
        print(f"[WARN] {w}")
    # raise or log depending on your strictness preference
```

---

## ABIS integration

The SKAT ABIS list (connector: `penge.connectors.abis`) determines whether a
fund is subject to lagerbeskatning.  When you refresh the ABIS list (see
[ABIS yearly refresh](../runbook/abis-yearly-refresh.md)), cross-check your
catalog's `tax_regime` values against the updated list:

* Instrument on ABIS list → `TaxRegime.LAGER` (when held in *frie midler*)
* Instrument removed from ABIS → change to `TaxRegime.REALISATION` and
  re-run projections; note the date of the change in `notes`.

---

## Immutability

`InstrumentAssumptions` is a **frozen dataclass** (`frozen=True`).  Once
created, its fields cannot be mutated.  This makes entries safe to share
across multiple projections or catalog instances without defensive copying.

To update an assumption, create a new `InstrumentAssumptions` object and call
`catalog.add()` with it; the old entry is replaced.
