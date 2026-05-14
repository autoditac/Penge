"""Investment assumption catalog for instruments and accounts.

This module provides a typed catalog of per-instrument assumptions used by the
household planner and liquid depot simulation.  Each entry captures the tax
regime, expense ratio (ÅOP), dividend yield, currency, and FX conversion cost
for a single instrument or account type so that projections do not hard-code
these values or duplicate them across scenarios.

## Supported tax regimes

* **TaxRegime.LAGER** — mark-to-market (lagerbeskatning); annual tax on
  unrealised gains.  Most Irish-domiciled UCITS ETFs on the ABIS list fall
  here when held in *frie midler*.
* **TaxRegime.REALISATION** — realisation-based (realisationsbeskatning);
  capital gains deferred until sale.  Dividends are taxed in the year
  received.
* **TaxRegime.ASK** — Aktiesparekonto flat-rate lager tax (17 %).  Only
  instruments eligible for ASK and held inside an ASK account belong here.

## Usage example

```python
from decimal import Decimal
from penge.sim.assumptions import AssumptionCatalog, InstrumentAssumptions, TaxRegime

catalog = AssumptionCatalog()
catalog.add(InstrumentAssumptions(
    isin="IE00B4L5Y983",
    label="iShares Core MSCI World UCITS ETF (Acc)",
    currency="EUR",
    tax_regime=TaxRegime.LAGER,
    expense_ratio=Decimal("0.002"),
    dividend_yield=Decimal("0"),
    ask_eligible=False,
    fx_cost=Decimal("0.0025"),
))
warnings = catalog.validate()
```

Design rationale: ``docs/sim/assumptions.md`` (issue #177).
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

__all__ = [
    "AssumptionCatalog",
    "InstrumentAssumptions",
    "TaxRegime",
]

_log = logging.getLogger(__name__)


class TaxRegime(enum.Enum):
    """Tax regime that governs how gains in an instrument or account are taxed.

    Attributes:
        LAGER: Mark-to-market annual tax (lagerbeskatning).
        REALISATION: Deferred capital-gain tax (realisationsbeskatning).
        ASK: Aktiesparekonto flat-rate lager tax (17 %).
    """

    LAGER = "lager"
    REALISATION = "realisation"
    ASK = "ask"


@dataclass(frozen=True)
class InstrumentAssumptions:
    """All assumptions for a single instrument or account type.

    Args:
        isin: ISIN or other unique identifier for the instrument.
        label: Human-readable name, e.g.
            ``"iShares Core MSCI World UCITS ETF (Acc)"``.
        currency: Native currency of the instrument; must be ``"EUR"`` or
            ``"DKK"``.  Validated at construction time.
        tax_regime: Tax regime that applies to gains in this instrument.
        expense_ratio: Annual total expense ratio (ÅOP) as a decimal
            fraction, e.g. ``Decimal("0.002")`` for 0.20 %.  Must be
            non-negative.
        dividend_yield: Expected annual dividend yield as a decimal fraction
            in ``[0, 1]``, e.g. ``Decimal("0.015")`` for 1.5 %.  Use
            ``Decimal("0")`` for accumulation-class funds.
        ask_eligible: ``True`` if the instrument is eligible for deposit
            into an ASK account.  Should be paired with
            ``tax_regime=TaxRegime.ASK`` when the instrument is actually
            held in ASK.
        fx_cost: One-way FX conversion cost per trade as a decimal fraction,
            e.g. ``Decimal("0.0025")`` for 0.25 %.  Should be
            ``Decimal("0")`` for DKK-denominated instruments unless there is
            an explicit reason.
        notes: Free-text explanation for manual overrides or non-obvious
            choices.
    """

    isin: str
    label: str
    currency: Literal["EUR", "DKK"]
    tax_regime: TaxRegime
    expense_ratio: Decimal
    dividend_yield: Decimal = Decimal("0")
    ask_eligible: bool = False
    fx_cost: Decimal = Decimal("0")
    notes: str = ""

    def __post_init__(self) -> None:
        if self.currency not in ("EUR", "DKK"):
            raise ValueError(f"currency must be 'EUR' or 'DKK' (got {self.currency!r})")
        if self.expense_ratio < 0:
            raise ValueError(f"expense_ratio cannot be negative (got {self.expense_ratio})")
        if not (Decimal("0") <= self.dividend_yield <= Decimal("1")):
            raise ValueError(f"dividend_yield must be between 0 and 1 (got {self.dividend_yield})")
        if self.fx_cost < 0:
            raise ValueError(f"fx_cost cannot be negative (got {self.fx_cost})")


@dataclass
class AssumptionCatalog:
    """Registry of instrument assumptions for the household planner.

    The catalog maps ISINs to :class:`InstrumentAssumptions` entries and
    exposes validation logic that surfaces missing or conflicting assumptions
    before a projection is run.

    Example::

        catalog = AssumptionCatalog()
        catalog.add(InstrumentAssumptions(...))
        entry = catalog.get("IE00B4L5Y983")
        warnings = catalog.validate()
    """

    _entries: dict[str, InstrumentAssumptions] = field(default_factory=dict, init=False)

    def add(self, assumptions: InstrumentAssumptions) -> None:
        """Add or overwrite an entry.

        If an entry for ``assumptions.isin`` already exists it is silently
        replaced; the caller is responsible for logging overrides via
        ``notes`` on the new entry.
        """
        if assumptions.isin in self._entries:
            _log.debug(
                "AssumptionCatalog: overwriting existing entry for ISIN %s",
                assumptions.isin,
            )
        self._entries[assumptions.isin] = assumptions

    def get(self, isin: str) -> InstrumentAssumptions:
        """Retrieve the assumptions for *isin*.

        Raises
        ------
        KeyError
            If no entry exists for the given ISIN.
        """
        return self._entries[isin]

    def get_or_none(self, isin: str) -> InstrumentAssumptions | None:
        """Return the assumptions for *isin*, or ``None`` if not found."""
        return self._entries.get(isin)

    def all(self) -> list[InstrumentAssumptions]:
        """Return all registered entries in insertion order."""
        return list(self._entries.values())

    def validate(self) -> list[str]:
        """Return a list of warning strings for suspicious or incomplete entries.

        Checks performed:

        * ``ask_eligible=True`` but ``tax_regime != TaxRegime.ASK``:
          ASK-eligible instruments should be cataloged under
          ``TaxRegime.ASK`` when they are held inside an ASK account.
        * ``tax_regime=TaxRegime.REALISATION`` with a very high
          ``dividend_yield`` (> 10 %): unusual combination worth reviewing.
        * ``currency="DKK"`` with ``fx_cost > 0``: DKK-denominated
          instruments should not incur FX cost unless there is a specific
          reason (e.g. custodian charges a DKK conversion fee).

        Returns
        -------
        list[str]
            Human-readable warning strings.  An empty list means the
            catalog looks clean.
        """
        warnings: list[str] = []
        for entry in self._entries.values():
            if entry.ask_eligible and entry.tax_regime != TaxRegime.ASK:
                warnings.append(
                    f"{entry.isin}: ask_eligible=True but "
                    f"tax_regime={entry.tax_regime!r}; "
                    "ASK-eligible instruments should use TaxRegime.ASK"
                )
            if entry.tax_regime == TaxRegime.REALISATION and entry.dividend_yield > Decimal("0.10"):
                warnings.append(
                    f"{entry.isin}: high dividend_yield ({entry.dividend_yield}) "
                    "on Realisation instrument"
                )
            if entry.currency == "DKK" and entry.fx_cost > Decimal("0"):
                warnings.append(
                    f"{entry.isin}: fx_cost set on DKK-denominated instrument; "
                    "verify this is intentional"
                )
        return warnings
