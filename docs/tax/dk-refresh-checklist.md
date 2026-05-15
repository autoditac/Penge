# DK Tax-Law Refresh Checklist

This page is the **annual runbook** for updating Penge's Danish planning
constants after SKAT and Ankestyrelsen publish their *satser* for the coming
year (typically November–December).

## When to run this checklist

| Trigger | Action |
|---------|--------|
| SKAT publishes *Satser for det kommende år* (usually Nov) | Update thresholds, caps, and rates below |
| Folkepension rates updated by Ankestyrelsen (usually Jan) | Update Folkepension amounts |
| Lov om regulering af pensioner (5-year review) | Update `FOLKEPENSION_AGE_SCHEDULE` |
| Any Danish tax law change affects a constant below | Open an ADR before updating the constant |

Run the freshness check after updating constants::

```bash
uv run python - <<'EOF'
import datetime
from penge.tax.dk.constants_meta import check_freshness

current = datetime.date.today().year
stale = check_freshness(current_year=current)
if stale:
    for m in stale:
        print(f"STALE  source={m.source_year}  {m.name}  [{m.module}.{m.constant}]")
else:
    print("All constants fresh.")
EOF
```

---

## Constant registry

All constants tracked by `penge.tax.dk.constants_meta.ALL_PLANNING_CONSTANTS`.
After updating a value in source code, update its `source_year` in
`constants_meta.py` as well.

### ASK (Aktiesparekonto)

| Constant | Module | Current value | Source year | Source |
|----------|--------|---------------|-------------|--------|
| `ASK_RATE` | `penge.tax.aktiesparekonto` | 17 % | 2026 | [skat.dk/aktiesparekonto](https://skat.dk/borger/aktier-og-investeringsbeviser/aktiesparekonto) |
| `ASK_DEPOSIT_CAPS` | `penge.tax.aktiesparekonto` | 142 500 DKK (2025, last confirmed) | 2025 | [skat.dk/satser](https://skat.dk/data/satser) |

!!! note "2026 ASK cap"
    The 2026 cumulative deposit ceiling is currently estimated at **148 000 DKK**
    in `penge.sim.liquid._ASK_DEPOSIT_CAPS_EXTENDED`.  Replace with the
    SKAT-confirmed value when it is published.

**How to update:**

1. Visit <https://skat.dk/data/satser> and locate *Aktiesparekonto — Indskudsgrænse*.
2. Add the new year → value pair to `ASK_DEPOSIT_CAPS` in
   `src/penge/tax/aktiesparekonto.py`.
3. Update `_ASK_DEPOSIT_CAPS_EXTENDED` in `src/penge/sim/liquid.py`.
4. Set `source_year` for `_ASK_DEPOSIT_CAPS` and `_ASK_RATE` in
   `src/penge/tax/dk/constants_meta.py`.

---

### PAL-skat

| Constant | Module | Current value | Source year | Source |
|----------|--------|---------------|-------------|--------|
| `PAL_RATE` | `penge.tax.pal` | 15.3 % | 2026 | [skat.dk/pensionsafkastskat](https://skat.dk/borger/pension/pensionsafkastskat) |

The PAL rate has been stable since the early 1990s.  Confirm the rate has not
changed and update `source_year` each year.

---

### Aktieindkomst (lagerbeskatning on ABIS ETFs)

| Constant | Module | Current value | Source year | Source |
|----------|--------|---------------|-------------|--------|
| `AKTIEINDKOMST_LOW_RATE` | `penge.sim.liquid` | 27 % | 2026 | [skattesatser-2026](https://skat.dk/data/satser/skattesatser-2026) |
| `AKTIEINDKOMST_HIGH_RATE` | `penge.sim.liquid` | 42 % | 2026 | [skattesatser-2026](https://skat.dk/data/satser/skattesatser-2026) |
| `AKTIEINDKOMST_THRESHOLDS` | `penge.sim.liquid` | 70 700 DKK/person (2026, estimated) | 2025 | [skat.dk/satser](https://skat.dk/data/satser) |

!!! warning "2026 threshold is estimated"
    The `AKTIEINDKOMST_THRESHOLDS[2026]` value of **70 700 DKK** is an estimate
    based on wage-index indexation.  Replace with the SKAT-confirmed value.

**How to update:**

1. Visit <https://skat.dk/data/satser> → *Aktieindkomst — Progressionsgrænse*.
2. Add the confirmed year → value to `AKTIEINDKOMST_THRESHOLDS` in
   `src/penge/sim/liquid.py`.
3. Set `source_year` for `_AKTIEINDKOMST_THRESHOLDS` in
   `src/penge/tax/dk/constants_meta.py`.

---

### Topskat

| Constant | Module | Current value | Source year | Source |
|----------|--------|---------------|-------------|--------|
| `DK_TOPSKAT_RATE` | `penge.tax.dk.rates` | 15 % | 2026 | [skattesatser-2026](https://skat.dk/data/satser/skattesatser-2026) |
| `DK_TOPSKAT_THRESHOLD_DKK` | `penge.tax.dk.rates` | 588 900 DKK | 2026 | [skattesatser-2026](https://skat.dk/data/satser/skattesatser-2026) |

**How to update:**

1. Visit <https://skat.dk/data/satser/skattesatser-{YEAR}>.
2. Locate *Topskat — Grænse* and *Topskat — Sats*.
3. Update `DK_TOPSKAT_RATE` and `DK_TOPSKAT_THRESHOLD_DKK` in
   `src/penge/tax/dk/rates.py`.
4. Update `source_year` in `constants_meta.py`.

---

### Folkepension

| Constant | Module | Current value | Source year | Source |
|----------|--------|---------------|-------------|--------|
| `FOLKEPENSION_GRUNDBELOEB_MONTHLY_DKK` | `penge.tax.dk.rates` | 7 191 DKK/month | 2026 | [ankestyrelsen.dk/satser](https://www.ankestyrelsen.dk/satser/satser-for-folkepension) |
| `FOLKEPENSION_TILLAEG_SINGLE_MONTHLY_DKK` | `penge.tax.dk.rates` | 18 389 DKK/month | 2026 | [ankestyrelsen.dk/satser](https://www.ankestyrelsen.dk/satser/satser-for-folkepension) |
| `FOLKEPENSION_TILLAEG_MARRIED_MONTHLY_DKK` | `penge.tax.dk.rates` | 8 993 DKK/month | 2026 | [ankestyrelsen.dk/satser](https://www.ankestyrelsen.dk/satser/satser-for-folkepension) |
| `FOLKEPENSION_MODREGNING_RATE` | `penge.tax.dk.rates` | 30.9 % | 2026 | [ankestyrelsen.dk/satser](https://www.ankestyrelsen.dk/satser/satser-for-folkepension) |
| `FOLKEPENSION_INCOME_THRESHOLD_DKK` | `penge.tax.dk.rates` | 94 800 DKK/year | 2026 | [ankestyrelsen.dk/satser](https://www.ankestyrelsen.dk/satser/satser-for-folkepension) |
| `FOLKEPENSION_AGE_SCHEDULE` | `penge.tax.dk.rates` | 67 (2026–2029), 68 (2030–2034), 69 (2035+) | 2026 | [borger.dk/folkepension](https://www.borger.dk/pension-og-efterloen/folkepension/Artikler/Hvornaar-kan-du-faa-folkepension) |

**How to update:**

1. Visit <https://www.ankestyrelsen.dk/satser/satser-for-folkepension> each January.
2. Compare *Grundbeløb*, *Pensionstillæg enkelt*, *Pensionstillæg gift*, and the
   modregning rate/threshold against the current constants.
3. Update `src/penge/tax/dk/rates.py` and set `source_year` in `constants_meta.py`.
4. The retirement-age schedule (`FOLKEPENSION_AGE_SCHEDULE`) is set by law and
   reviewed every 5 years.  Monitor *Velfærdsaftalen* for changes.

---

## After updating any constant

1. Run `just test` — all existing tests must pass.
2. Run `just lint` — mypy must accept all types.
3. Commit with `chore(tax): refresh DK constants for {YEAR}`.
4. Open a PR and reference this checklist in the PR description.
5. If the change is **material** (a rate or threshold changed by more than 1 %
   of its value), open an ADR in `docs/decisions/` before merging.

---

## See also

- [`docs/tax/dk.md`](dk.md) — simulation model documentation
- [`penge.tax.dk.constants_meta`](https://github.com/autoditac/Penge/blob/main/src/penge/tax/dk/constants_meta.py) — Python metadata registry
- [`penge.sim.registry`](https://github.com/autoditac/Penge/blob/main/src/penge/sim/registry.py) — audit record builder
- [ADR-0013](../decisions/0013-sim-tax-overlay.md) — tax overlay design
- [ADR-0018](../decisions/0018-aktiesparekonto-handling.md) — ASK handling
