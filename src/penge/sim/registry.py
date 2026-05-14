"""Assumption registry and projection audit record.

Every projection run should be accompanied by an :class:`ProjectionAuditRecord`
that snapshots *all* constants, rates, and model versions used during that run.
This makes results reproducible and auditable: running the same scenario a year
later with updated tax constants will produce a different record, and diffing
the two records immediately shows which inputs changed.

## Usage

Build a standard record (captures built-in constants from tax and liquid
modules):

```python
from penge.sim.registry import build_standard_audit_record, AssumptionEntry

record = build_standard_audit_record(run_id="2025-01-baseline")
print(record.to_markdown())
print(record.to_json())
```

Add your own scenario-specific entries:

```python
record = build_standard_audit_record(
    run_id="2025-01-baseline",
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
            value="7.46",
            unit="DKK per EUR",
            source="ECB 2025-01-01",
        ),
    ],
)
```

Round-trip to/from JSON (for storage in a report artefact):

```python
serialized = record.to_json()
restored = ProjectionAuditRecord.from_json(serialized)
assert restored == record
```

## Design rationale

* :class:`AssumptionEntry` holds a **string** ``value`` so that
  :meth:`ProjectionAuditRecord.to_json` never needs a custom JSON encoder.
  The caller converts Decimal/int/float values to ``str`` before creating an
  entry.
* :class:`ProjectionAuditRecord` is a plain dataclass (not Pydantic) so it
  has no runtime dependency beyond the standard library.
* :func:`build_standard_audit_record` imports the actual constant objects
  (e.g. :data:`~penge.sim.liquid.AKTIEINDKOMST_LOW_RATE`) at call time, so
  the registry automatically reflects any future constant updates.

See ``docs/sim/registry.md`` for the full audit contract.
See ``docs/decisions/0013-sim-tax-overlay.md`` (ADR-0013) and
``docs/decisions/0018-aktiesparekonto-handling.md`` (ADR-0018) for background.
"""

from __future__ import annotations

import datetime
import json
import logging
from dataclasses import asdict, dataclass, field
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

from penge.sim.liquid import (
    AKTIEINDKOMST_HIGH_RATE,
    AKTIEINDKOMST_LOW_RATE,
    AKTIEINDKOMST_THRESHOLDS,
)
from penge.sim.tax import DE_DEFAULT, DK_DEFAULT
from penge.tax.aktiesparekonto import ASK_DEPOSIT_CAPS, ASK_RATE

__all__ = [
    "AssumptionEntry",
    "ProjectionAuditRecord",
    "build_standard_audit_record",
]

_log = logging.getLogger(__name__)


@dataclass
class AssumptionEntry:
    """A single named assumption with value, unit, source, and ADR reference.

    Args:
        name: Human-readable assumption name,
            e.g. ``"DK PAL-skat rate"``.
        value: The assumption value serialised as a string,
            e.g. ``"15.3"`` or ``"142500"``.  Always ``str`` so that
            JSON round-trips are trivial.
        unit: Dimension / unit of the value, e.g. ``"%"``, ``"DKK"``,
            ``"EUR"``, ``"fraction"``, ``"years"``.
        source: Where this value comes from, e.g. ``"SKAT 2025"``,
            ``"ECB"``, ``"hardcoded"``, ``"user input"``.
        adr: Optional ADR reference, e.g. ``"ADR-0013"``.
        notes: Optional free-text annotation.
    """

    name: str
    value: str
    unit: str
    source: str
    adr: str = ""
    notes: str = ""


@dataclass
class ProjectionAuditRecord:
    """Snapshot of all assumptions used during a single projection run.

    Args:
        run_id: Stable identifier for this run, e.g. an ISO-8601 timestamp
            or a human label like ``"2025-01-baseline"``.  Defaults to an
            ISO-8601 UTC timestamp if not supplied by the caller.
        captured_at: ISO-8601 UTC datetime at which this record was created.
        penge_version: The installed ``penge`` package version string at
            capture time (``"dev"`` when running from source without a
            release tag).
        assumptions: Ordered list of :class:`AssumptionEntry` objects.
    """

    run_id: str
    captured_at: str
    penge_version: str
    assumptions: list[AssumptionEntry] = field(default_factory=list)

    def add(self, entry: AssumptionEntry) -> None:
        """Append *entry* to the assumption list."""
        self.assumptions.append(entry)

    def to_json(self) -> str:
        """Serialise the record to a formatted JSON string.

        The result can be written to a report artefact and later
        restored via :meth:`from_json`.
        """
        return json.dumps(asdict(self), indent=2, ensure_ascii=False)

    def to_markdown(self) -> str:
        """Render the record as a Markdown document with a table.

        Returns a string that starts with a level-1 heading and contains
        a pipe-delimited Markdown table of all assumptions.
        """
        lines: list[str] = [
            f"# Projection audit: {self.run_id}",
            "",
            f"Captured: {self.captured_at}  ",
            f"Penge version: {self.penge_version}",
            "",
            "| Assumption | Value | Unit | Source | ADR | Notes |",
            "|---|---|---|---|---|---|",
        ]
        for a in self.assumptions:
            lines.append(f"| {a.name} | {a.value} | {a.unit} | {a.source} | {a.adr} | {a.notes} |")
        return "\n".join(lines)

    @classmethod
    def from_json(cls, data: str) -> ProjectionAuditRecord:
        """Deserialise a record from a JSON string produced by :meth:`to_json`.

        Args:
            data: JSON string as produced by :meth:`to_json`.

        Returns:
            A fully reconstructed :class:`ProjectionAuditRecord`.

        Raises:
            json.JSONDecodeError: If *data* is not valid JSON.
            KeyError: If required fields are missing from the JSON.
        """
        d: dict[str, object] = json.loads(data)
        raw_assumptions = d.pop("assumptions")
        if not isinstance(raw_assumptions, list):
            raise ValueError("'assumptions' must be a JSON array")
        # Each element is a dict produced by json.loads — keys/values are str.
        entries = [AssumptionEntry(**e) for e in raw_assumptions]
        record = cls(**d)  # type: ignore[arg-type]  # runtime-safe: remaining keys match ProjectionAuditRecord fields
        record.assumptions = entries
        return record


def build_standard_audit_record(
    run_id: str = "",
    *,
    extra_entries: list[AssumptionEntry] | None = None,
) -> ProjectionAuditRecord:
    """Build a standard audit record capturing Penge's built-in constants.

    All monetary and rate constants are read at call time from the
    authoritative source modules (:mod:`penge.sim.tax`,
    :mod:`penge.sim.liquid`, :mod:`penge.tax.aktiesparekonto`) so that
    the record always reflects the currently installed values.

    Args:
        run_id: Optional stable identifier for this projection run.
            Defaults to the UTC ISO-8601 timestamp at call time.
        extra_entries: Additional :class:`AssumptionEntry` items supplied
            by the caller (e.g. FX rates, expected returns, scenario
            parameters).  Appended after the standard entries.

    Returns:
        A populated :class:`ProjectionAuditRecord`.
    """
    # Import version lazily to avoid hard-coding it here.
    try:
        penge_ver = _pkg_version("penge")
    except PackageNotFoundError:  # pragma: no cover — running from source
        penge_ver = "dev"

    now = datetime.datetime.now(datetime.UTC).isoformat()
    record = ProjectionAuditRecord(
        run_id=run_id or now,
        captured_at=now,
        penge_version=penge_ver,
    )

    # ── Denmark — PAL-skat (pension return tax) ──────────────────────────────
    record.add(
        AssumptionEntry(
            name="DK PAL-skat rate",
            value=str(DK_DEFAULT.pension_return_tax_rate * 100),
            unit="%",
            source="SKAT 2025",
            adr="ADR-0013",
            notes="Annual tax on pension-pot returns (withheld by PFA)",
        )
    )

    # ── Denmark — income tax ─────────────────────────────────────────────────
    record.add(
        AssumptionEntry(
            name="DK top-marginal salary income tax rate",
            value=str(DK_DEFAULT.salary_income_tax_rate * 100),
            unit="%",
            source="SKAT 2025",
            adr="ADR-0013",
            notes="Bundskat + topskat + kommuneskat for salary > ~590k DKK",
        )
    )
    record.add(
        AssumptionEntry(
            name="DK pension drawdown tax rate",
            value=str(DK_DEFAULT.pension_drawdown_tax_rate * 100),
            unit="%",
            source="SKAT 2025",
            adr="ADR-0013",
            notes="Expected marginal rate in retirement (DK_DEFAULT)",
        )
    )

    # ── Denmark — Lagerbeskatning (aktieindkomst) ─────────────────────────────
    record.add(
        AssumptionEntry(
            name="DK Lagerbeskatning low rate",
            value=str(AKTIEINDKOMST_LOW_RATE * 100),
            unit="%",
            source="SKAT 2025",
            adr="ADR-0013",
            notes="Annual mark-to-market rate on gains up to threshold",
        )
    )
    record.add(
        AssumptionEntry(
            name="DK Lagerbeskatning high rate",
            value=str(AKTIEINDKOMST_HIGH_RATE * 100),
            unit="%",
            source="SKAT 2025",
            adr="ADR-0013",
            notes="Annual mark-to-market rate on gains above threshold",
        )
    )

    # Threshold: use the latest known year.
    latest_threshold_year = max(AKTIEINDKOMST_THRESHOLDS)
    latest_threshold = AKTIEINDKOMST_THRESHOLDS[latest_threshold_year]
    record.add(
        AssumptionEntry(
            name=f"DK Aktieindkomst threshold per person ({latest_threshold_year})",
            value=str(latest_threshold),
            unit="DKK",
            source="SKAT 2025",
            adr="ADR-0013",
            notes="Gains above this are taxed at the high rate; indexed annually",
        )
    )

    # DK capital gains effective rate used by default regime
    record.add(
        AssumptionEntry(
            name="DK capital gains effective rate (DK_DEFAULT)",
            value=str(DK_DEFAULT.capital_gains_effective_rate * 100),
            unit="%",
            source="SKAT 2025",
            adr="ADR-0013",
            notes=(
                "Lagerbeskatning at lower bracket rate; raise to 42% "
                "if projected annual gain exceeds threshold"
            ),
        )
    )

    # ── Denmark — ASK ────────────────────────────────────────────────────────
    record.add(
        AssumptionEntry(
            name="DK ASK tax rate",
            value=str(ASK_RATE * 100),
            unit="%",
            source="SKAT 2025",
            adr="ADR-0018",
            notes="Flat annual mark-to-market rate inside Aktiesparekonto",
        )
    )

    latest_ask_year = max(ASK_DEPOSIT_CAPS)
    latest_ask_cap = ASK_DEPOSIT_CAPS[latest_ask_year]
    record.add(
        AssumptionEntry(
            name=f"DK ASK cumulative deposit cap ({latest_ask_year})",
            value=str(latest_ask_cap),
            unit="DKK",
            source="SKAT 2025",
            adr="ADR-0018",
            notes="Lifetime net-deposit ceiling; indexed annually by SKAT",
        )
    )

    # ── Germany — income tax ─────────────────────────────────────────────────
    record.add(
        AssumptionEntry(
            name="DE salary income tax rate (DE_DEFAULT)",
            value=str(DE_DEFAULT.salary_income_tax_rate * 100),
            unit="%",
            source="EStG Splittingtarif",
            adr="ADR-0013",
            notes="Approximate marginal Splittingtarif for combined household income",
        )
    )
    record.add(
        AssumptionEntry(
            name="DE pension return tax rate (DE_DEFAULT)",
            value=str(DE_DEFAULT.pension_return_tax_rate * 100),
            unit="%",
            source="EStG",
            adr="ADR-0013",
            notes="0% during accumulation for Beamtenpension (no sheltered pot)",
        )
    )
    record.add(
        AssumptionEntry(
            name="DE pension drawdown tax rate (DE_DEFAULT)",
            value=str(DE_DEFAULT.pension_drawdown_tax_rate * 100),
            unit="%",
            source="EStG §22",
            adr="ADR-0013",
            notes="Ertragsanteil / Besteuerungsanteil regime at drawdown",
        )
    )

    # ── Germany — capital gains ───────────────────────────────────────────────
    record.add(
        AssumptionEntry(
            name="DE Abgeltungsteuer gross rate",
            value="25",
            unit="%",
            source="EStG §32d",
            adr="ADR-0013",
            notes="Flat rate on capital income; plus Solidaritätszuschlag",
        )
    )
    record.add(
        AssumptionEntry(
            name="DE Solidaritätszuschlag on Abgeltungsteuer",
            value="5.5",
            unit="%",
            source="SolZG",
            adr="ADR-0013",
            notes="5.5% of Abgeltungsteuer → combined 26.375%",
        )
    )
    record.add(
        AssumptionEntry(
            name="DE Teilfreistellung equity funds",
            value="30",
            unit="%",
            source="InvStG §20",
            adr="ADR-0013",
            notes="30% of gain on equity UCITS funds is tax-free",
        )
    )
    record.add(
        AssumptionEntry(
            name="DE capital gains effective rate (DE_DEFAULT)",
            value=str(DE_DEFAULT.capital_gains_effective_rate * 100),
            unit="%",
            source="EStG §32d + InvStG §20",
            adr="ADR-0013",
            notes=(
                "Abgeltungsteuer 26.375% * 0.70 (30% Teilfreistellung); ignores Sparerpauschbetrag"
            ),
        )
    )

    if extra_entries:
        for entry in extra_entries:
            record.add(entry)
        _log.debug("build_standard_audit_record: added %d extra entries", len(extra_entries))

    return record
