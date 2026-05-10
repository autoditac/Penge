"""Danish lagerbeskatning (mark-to-market) calculator.

Computes the annual taxable gain/loss per (account_id, ISIN) for
instruments classified as ``DK_TAX_LAGERBESKATNING`` (i.e. on the
ABIS list — Aktiebaserede Investeringsselskaber).

Formula (per ISIN, per tax year):

    gain = end_market_value
         - start_market_value
         - sum(buys.cost)
         + sum(sells.proceeds)
         + sum(distributions)

Where:

* ``start_market_value`` is the holding's value on 31 December of the
  prior year, in DKK at the SKAT-published year-end FX rate.
* ``end_market_value`` is the holding's value on 31 December of the
  tax year, in DKK at the SKAT-published year-end FX rate.
* ``buys.cost`` and ``sells.proceeds`` are the trade-date amounts in
  DKK (caller is responsible for FX conversion to DKK).
* ``distributions`` are taxable cash distributions paid in the year
  (in DKK).

All inputs and outputs are ``Money`` in DKK. Mixing currencies inside
a single calculation raises :class:`LagerError`. Caller converts to
DKK using the appropriate FX source before constructing inputs.

This module classifies a yearly result as taxable kapitalindkomst.
The SKAT progressive bands (≤ 61 900 DKK @ 27 %, > 61 900 DKK @ 42 %
in 2024) apply to the *household total* of capital income, not per
ISIN; band application is done by the SKAT report generator (#39).

References:

* SKAT — `Aktier og investeringsbeviser
  <https://skat.dk/borger/aktier-og-investeringsbeviser>`_
* :doc:`/tax/dk` — Lagerbeskatning section
* ADR-0017 — Lagerbeskatning calculator
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from decimal import ROUND_HALF_EVEN, Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from penge.tax.lots import Money

__all__ = [
    "BuyLeg",
    "Distribution",
    "LagerError",
    "LagerInput",
    "LagerResult",
    "SellLeg",
    "compute_lager",
    "compute_lager_many",
    "sum_gain_by_year",
]

from typing import Final, Literal

_MONEY_DP = Decimal("0.01")
_DKK: Final[Literal["DKK"]] = "DKK"


def _q(value: Decimal) -> Decimal:
    return value.quantize(_MONEY_DP, rounding=ROUND_HALF_EVEN)


class LagerError(Exception):
    """Raised when a lager input is inconsistent (e.g. wrong currency)."""


def _ensure_dkk_nonneg(v: Money, *, label: str) -> Money:
    if v.currency != _DKK:
        raise LagerError(f"{label} must be DKK, got {v.currency}")
    if v.amount < 0:
        raise LagerError(f"{label} must be non-negative")
    return v


class BuyLeg(BaseModel):
    """A buy executed during the tax year, in DKK."""

    model_config = ConfigDict(frozen=True)

    cost: Money = Field(..., description="Total cost in DKK (price * qty + fees).")

    @field_validator("cost")
    @classmethod
    def _dkk(cls, v: Money) -> Money:
        return _ensure_dkk_nonneg(v, label="BuyLeg.cost")


class SellLeg(BaseModel):
    """A sell executed during the tax year, in DKK."""

    model_config = ConfigDict(frozen=True)

    proceeds: Money = Field(..., description="Net proceeds in DKK after fees.")

    @field_validator("proceeds")
    @classmethod
    def _dkk(cls, v: Money) -> Money:
        return _ensure_dkk_nonneg(v, label="SellLeg.proceeds")


class Distribution(BaseModel):
    """A taxable cash distribution paid during the tax year, in DKK."""

    model_config = ConfigDict(frozen=True)

    amount: Money

    @field_validator("amount")
    @classmethod
    def _dkk(cls, v: Money) -> Money:
        return _ensure_dkk_nonneg(v, label="Distribution.amount")


class LagerInput(BaseModel):
    """All data required to compute lagerbeskatning for one ISIN, one year."""

    model_config = ConfigDict(frozen=True)

    account_id: str = Field(..., min_length=1)
    isin: str = Field(..., min_length=12, max_length=12)
    tax_year: int = Field(..., ge=1900, le=2999)
    start_market_value: Money
    end_market_value: Money
    buys: tuple[BuyLeg, ...] = ()
    sells: tuple[SellLeg, ...] = ()
    distributions: tuple[Distribution, ...] = ()

    @field_validator("start_market_value", "end_market_value")
    @classmethod
    def _mv_dkk(cls, v: Money) -> Money:
        return _ensure_dkk_nonneg(v, label="market value")


class LagerResult(BaseModel):
    """Per-ISIN, per-year lagerbeskatning gain/loss in DKK."""

    model_config = ConfigDict(frozen=True)

    account_id: str
    isin: str
    tax_year: int
    start_market_value: Money
    end_market_value: Money
    buys_total: Money
    sells_total: Money
    distributions_total: Money
    gain: Money
    """Positive = taxable gain, negative = deductible loss."""


def compute_lager(inp: LagerInput) -> LagerResult:
    """Compute the lager gain/loss for one ISIN in one tax year.

    Pure function — no I/O, no FX. Caller must have converted all
    monetary inputs to DKK (typically via SKAT-published year-end FX
    rates for market values and trade-date rates for legs).
    """

    buys_sum = sum((b.cost.amount for b in inp.buys), Decimal("0"))
    sells_sum = sum((s.proceeds.amount for s in inp.sells), Decimal("0"))
    dist_sum = sum((d.amount.amount for d in inp.distributions), Decimal("0"))

    gain = (
        inp.end_market_value.amount
        - inp.start_market_value.amount
        - buys_sum
        + sells_sum
        + dist_sum
    )

    return LagerResult(
        account_id=inp.account_id,
        isin=inp.isin,
        tax_year=inp.tax_year,
        start_market_value=Money(amount=_q(inp.start_market_value.amount), currency=_DKK),
        end_market_value=Money(amount=_q(inp.end_market_value.amount), currency=_DKK),
        buys_total=Money(amount=_q(buys_sum), currency=_DKK),
        sells_total=Money(amount=_q(sells_sum), currency=_DKK),
        distributions_total=Money(amount=_q(dist_sum), currency=_DKK),
        gain=Money(amount=_q(gain), currency=_DKK),
    )


def compute_lager_many(inputs: Iterable[LagerInput]) -> list[LagerResult]:
    """Convenience wrapper computing per-input results.

    Inputs are processed independently. The returned list preserves
    input order. Use :func:`sum_gain_by_year` (or simple aggregation
    on the result list) to obtain household totals before applying
    the kapitalindkomst progressive bands.
    """

    return [compute_lager(i) for i in inputs]


def sum_gain_by_year(results: Iterable[LagerResult]) -> dict[int, Money]:
    """Aggregate gain across results by tax year (DKK)."""

    totals: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    for r in results:
        totals[r.tax_year] += r.gain.amount
    return {y: Money(amount=_q(v), currency=_DKK) for y, v in totals.items()}
