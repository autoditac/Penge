# Assumption registry and projection audit record

Every projection run in Penge can be accompanied by a
`ProjectionAuditRecord` that snapshots **all** constants, rates, model
versions, and user-supplied assumptions used during that run.

This makes long-term projections reproducible and auditable: if you run
the same scenario a year later and the numbers change, a diff of the two
records immediately shows which inputs changed (e.g. an updated tax
threshold or a different expected-return assumption).

---

## Concepts

| Concept | Class / function | Description |
|---|---|---|
| Single assumption | `AssumptionEntry` | One named constant: value, unit, source, optional ADR link |
| Audit snapshot | `ProjectionAuditRecord` | Ordered collection of entries + run metadata |
| Standard factory | `build_standard_audit_record()` | Builds a record from Penge's built-in constants |

### `AssumptionEntry`

```python
@dataclass
class AssumptionEntry:
    name: str     # e.g. "DK PAL-skat rate"
    value: str    # always str — JSON round-trips are trivial
    unit: str     # e.g. "%", "DKK", "EUR", "fraction"
    source: str   # e.g. "SKAT 2025", "ECB", "user input"
    adr: str = "" # e.g. "ADR-0013"
    notes: str = ""
```

`value` is always a `str` so that the record serialises to JSON without
a custom encoder.  Convert `Decimal` or numeric values before creating an
entry: `value=str(my_decimal)`.

### `ProjectionAuditRecord`

```python
@dataclass
class ProjectionAuditRecord:
    run_id: str           # stable label for this run
    captured_at: str      # ISO-8601 UTC datetime
    penge_version: str    # importlib.metadata version at capture time
    assumptions: list[AssumptionEntry]
```

The `penge_version` field records which release of the Penge package
generated the record.  If you upgrade Penge and re-run the same scenario,
the version difference in the record is an immediate signal to re-check all
constants.  It is set to `"dev"` when running from source without an
installed release.

---

## Quick start

### Build a standard record

```python
from penge.sim.registry import build_standard_audit_record

record = build_standard_audit_record(run_id="2025-01-baseline")
```

`build_standard_audit_record` accesses the **current values** of constants at
call time from the authoritative source modules (`penge.sim.tax`,
`penge.sim.liquid`, `penge.tax.aktiesparekonto`).  The modules are imported once
at package load, but the constant values are looked up when the function is
called — so the record always reflects the installed values, with no magic
numbers.

### Serialize to JSON

```python
json_str = record.to_json()
# write to disk, attach to a report, store in a database …
with open("audit_2025-01.json", "w") as f:
    f.write(json_str)
```

### Render as Markdown

```python
md = record.to_markdown()
print(md)
```

Output example:

```text
# Projection audit: 2025-01-baseline

Captured: 2025-01-15T08:30:00+00:00
Penge version: 1.2.3

| Assumption | Value | Unit | Source | ADR | Notes |
|---|---|---|---|---|---|
| DK PAL-skat rate | 15.3 | % | SKAT 2025 | ADR-0013 | Annual tax on pension-pot returns (withheld by PFA) |
| DK ASK tax rate | 17 | % | SKAT 2025 | ADR-0018 | Flat annual mark-to-market rate inside Aktiesparekonto |
…
```

### Add custom (scenario-specific) entries

Pass `extra_entries` to append your own assumptions after the standard ones:

```python
from decimal import Decimal
from penge.sim.registry import AssumptionEntry, build_standard_audit_record

record = build_standard_audit_record(
    run_id="2025-01-optimistic",
    extra_entries=[
        AssumptionEntry(
            name="Portfolio expected real return",
            value="5.5",
            unit="%",
            source="user input",
            notes="MSCI World 30-year geometric mean estimate",
        ),
        AssumptionEntry(
            name="EUR/DKK FX rate",
            value=str(Decimal("7.4604")),
            unit="DKK per EUR",
            source="ECB 2025-01-01",
        ),
        AssumptionEntry(
            name="Inflation assumption",
            value="2.0",
            unit="%",
            source="ECB target",
            notes="Used to deflate nominal returns",
        ),
    ],
)
```

You can also build a record entirely from scratch:

```python
from penge.sim.registry import AssumptionEntry, ProjectionAuditRecord
import datetime

record = ProjectionAuditRecord(
    run_id="manual-run",
    captured_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    penge_version="dev",
)
record.add(AssumptionEntry(name="My rate", value="3.5", unit="%", source="estimate"))
```

---

## Restore from JSON

```python
from penge.sim.registry import ProjectionAuditRecord

with open("audit_2025-01.json") as f:
    restored = ProjectionAuditRecord.from_json(f.read())

assert restored.run_id == "2025-01-baseline"
```

---

## Compare two records (diff)

The registry does not provide a built-in diff utility, but you can compare
two records with standard Python:

```python
def diff_records(
    before: ProjectionAuditRecord,
    after: ProjectionAuditRecord,
) -> list[str]:
    """Return lines describing changed / added / removed assumptions."""
    before_map = {e.name: e for e in before.assumptions}
    after_map = {e.name: e for e in after.assumptions}
    lines = []
    all_names = sorted(before_map.keys() | after_map.keys())
    for name in all_names:
        b = before_map.get(name)
        a = after_map.get(name)
        if b is None:
            lines.append(f"+ ADDED   {name} = {a.value} {a.unit}")
        elif a is None:
            lines.append(f"- REMOVED {name} = {b.value} {b.unit}")
        elif b.value != a.value:
            lines.append(
                f"~ CHANGED {name}: {b.value} {b.unit} → {a.value} {a.unit}"
            )
    return lines


before = ProjectionAuditRecord.from_json(open("audit_2024-12.json").read())
after  = ProjectionAuditRecord.from_json(open("audit_2025-01.json").read())
for line in diff_records(before, after):
    print(line)
```

Example output after a SKAT threshold update:

```text
~ CHANGED DK Aktieindkomst threshold per person (2026): 70700 DKK → 73100 DKK
```

---

## Standard entries captured by `build_standard_audit_record`

The factory captures the following categories of assumptions:

| Category | Key entries |
|---|---|
| DK pension | PAL-skat rate (15.3%), salary income tax rate, pension drawdown rate |
| DK Lagerbeskatning | Low rate (27%), high rate (42%), aktieindkomst threshold (per-person, DKK) |
| DK capital gains effective (DK_DEFAULT) | Effective rate for the default DK regime |
| DK ASK | ASK rate (17%), cumulative deposit cap (DKK, latest confirmed year) |
| DE income tax | Salary rate, pension return rate, pension drawdown rate |
| DE capital gains | Abgeltungsteuer gross (25%), Solidaritätszuschlag (5.5%), Teilfreistellung (30%), effective rate |

All monetary values are in **DKK** or **EUR** as labelled; all rates are in
**%** (not fractions) so that audit output is human-readable without mental
conversion.

---

## ADR references

- [ADR-0013 — Sim tax overlay](../decisions/0013-sim-tax-overlay.md) —
  tax-rate constants for DK and DE.
- [ADR-0018 — Aktiesparekonto handling](../decisions/0018-aktiesparekonto-handling.md) —
  ASK rate and deposit-cap constants.
- [ADR-0027 — Liquid depot simulation model](../decisions/0027-liquid-depot-simulation-model.md) —
  lagerbeskatning rates and aktieindkomst thresholds.
