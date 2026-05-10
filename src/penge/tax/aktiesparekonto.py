"""Aktiesparekonto (ASK) — flat 17 % lagerbeskatning wrapper.

The ASK is a separate Danish tax wrapper introduced in 2019. It taxes
all holdings annually on a mark-to-market basis at a flat **17 %**
(no progressive bands), and limits *cumulative* (lifetime) net deposits
to a yearly-indexed cap. The cap that applies at any moment is the cap
of the calendar year in which the deposit is made — see
:data:`ASK_DEPOSIT_CAPS` for the current values.

This module provides:

* :func:`compute_ask_tax` — applies the 17 % rate to a per-ISIN
  :class:`~penge.tax.lager.LagerResult`. Negative gains (losses) are
  carried forward (returned as a deductible amount, with zero tax due
  for the year). The ASK loss carry-forward bookkeeping itself is
  the SKAT report's responsibility (#39).
* :func:`compute_ask_taxes` — sums per-ISIN results into one yearly
  ASK tax figure, applying the 17 % rate to the *aggregate* gain so
  that intra-account losses net against gains in the same year.
* :func:`check_deposit_cap` — verifies that cumulative net deposits
  on an ASK account stay within the yearly cap.

References:

* SKAT — `Aktiesparekonto
  <https://skat.dk/borger/aktier-og-investeringsbeviser/aktiesparekonto>`_
* :doc:`/tax/dk` — Aktiesparekonto section
* ADR-0018 — Aktiesparekonto handling
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from penge.tax.lager import LagerResult
from penge.tax.lots import Money

__all__ = [
    "ASK_DEPOSIT_CAPS",
    "ASK_RATE",
    "AskDeposit",
    "AskError",
    "AskTaxResult",
    "check_deposit_cap",
    "compute_ask_tax",
    "compute_ask_taxes",
]

_MONEY_DP = Decimal("0.01")
_DKK: Final[Literal["DKK"]] = "DKK"

ASK_RATE: Final = Decimal("0.17")
"""Flat ASK tax rate (17 %) on annual mark-to-market gains."""

ASK_DEPOSIT_CAPS: Final[Mapping[int, Decimal]] = {
    2019: Decimal("50000"),
    2020: Decimal("100000"),
    2021: Decimal("102300"),
    2022: Decimal("103500"),
    2023: Decimal("106600"),
    2024: Decimal("135900"),
    2025: Decimal("142500"),
}
"""SKAT-published cumulative net-deposit caps per year (DKK).

Keep this table in sync with SKAT's annual indexing announcement.
Used by :func:`check_deposit_cap`. Years outside the table raise
``AskError`` so the caller is forced to update the constants.
"""


def _q(value: Decimal) -> Decimal:
    return value.quantize(_MONEY_DP, rounding=ROUND_HALF_EVEN)


class AskError(Exception):
    """Raised on ASK rule violations (wrong currency, cap breached, ...)."""


class AskDeposit(BaseModel):
    """A net deposit movement on an ASK account.

    Negative ``amount`` represents a withdrawal. The Danish ASK rule
    applies to the *cumulative* (lifetime) net-deposit total: that
    running total must never exceed the cap of the calendar year in
    which a deposit is made. See :data:`ASK_DEPOSIT_CAPS` and
    :func:`check_deposit_cap`.
    """

    model_config = ConfigDict(frozen=True)

    year: int = Field(..., ge=2019, le=2999)
    amount: Money

    @field_validator("amount")
    @classmethod
    def _dkk(cls, v: Money) -> Money:
        if v.currency != _DKK:
            raise AskError(f"AskDeposit.amount must be DKK, got {v.currency}")
        return v


class AskTaxResult(BaseModel):
    """Per-year ASK tax result in DKK."""

    model_config = ConfigDict(frozen=True)

    account_id: str
    tax_year: int
    gain: Money
    """Net taxable gain across all ISINs on the account (DKK)."""

    tax_due: Money
    """17 % of ``gain`` if positive, otherwise 0 DKK."""

    loss_carry_forward: Money
    """Magnitude of the negative gain available for future-year offset (DKK)."""


def compute_ask_taxes(
    *,
    account_id: str,
    tax_year: int,
    lager_results: Iterable[LagerResult],
) -> AskTaxResult:
    """Aggregate per-ISIN lager results and apply the 17 % ASK rate.

    Losses on one ISIN net against gains on another *within the same
    year and account*; only the residual positive amount is taxed.
    Negative residuals are reported as ``loss_carry_forward`` (the
    actual carry-forward bookkeeping across years is the SKAT report
    generator's job — see #39).
    """

    gain = Decimal("0")
    for r in lager_results:
        if r.account_id != account_id:
            raise AskError(
                f"lager result for account {r.account_id!r} passed to ASK "
                f"calculator for account {account_id!r}"
            )
        if r.tax_year != tax_year:
            raise AskError(
                f"lager result for tax year {r.tax_year} passed to ASK "
                f"calculator for tax year {tax_year}"
            )
        if r.gain.currency != _DKK:
            raise AskError(
                f"lager result gain must be DKK, got {r.gain.currency} "
                f"(account {account_id!r}, isin {r.isin!r})"
            )
        gain += r.gain.amount

    if gain >= 0:
        tax = gain * ASK_RATE
        loss = Decimal("0")
    else:
        tax = Decimal("0")
        loss = -gain

    return AskTaxResult(
        account_id=account_id,
        tax_year=tax_year,
        gain=Money(amount=_q(gain), currency=_DKK),
        tax_due=Money(amount=_q(tax), currency=_DKK),
        loss_carry_forward=Money(amount=_q(loss), currency=_DKK),
    )


def compute_ask_tax(*, account_id: str, lager_result: LagerResult) -> AskTaxResult:
    """Convenience for a single-ISIN ASK account."""

    return compute_ask_taxes(
        account_id=account_id,
        tax_year=lager_result.tax_year,
        lager_results=[lager_result],
    )


def check_deposit_cap(
    *,
    account_id: str,
    deposits: Iterable[AskDeposit],
) -> None:
    """Raise :class:`AskError` if cumulative net deposits exceed the cap.

    The ASK rule is on **cumulative** net deposits across the lifetime
    of the account, not per-year. The cap is whatever year's cap is
    currently in force at any given point in time. We check the
    running total against the cap of each year as deposits are walked
    in chronological order.
    """

    sorted_deposits = sorted(deposits, key=lambda d: d.year)
    running = Decimal("0")
    for dep in sorted_deposits:
        if dep.year not in ASK_DEPOSIT_CAPS:
            raise AskError(
                f"no ASK deposit cap configured for year {dep.year}; " f"update ASK_DEPOSIT_CAPS"
            )
        running += dep.amount.amount
        cap = ASK_DEPOSIT_CAPS[dep.year]
        if running > cap:
            raise AskError(
                f"ASK account {account_id!r}: cumulative net deposits "
                f"{running} DKK exceed {dep.year} cap {cap} DKK"
            )
