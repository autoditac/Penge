"""Decumulation phase — Livrente and Ratepension payout modelling.

Danish occupational pensions (e.g. PFA) split at retirement into three products:

**Livrente** (lifelong annuity)
    Paid monthly until death (with a guaranteed minimum period set by the
    provider).  The gross monthly amount is determined by an *annuity factor*
    (*omregningsfaktor*) published annually by the pension provider and
    Finanstilsynet.  A planning default is ~3 800-4 200 kr/month per 1 000 000
    kr of capital at age 67.

**Ratepension** (fixed-term drawdown)
    Paid monthly over a period chosen at retirement (10-30 years).  The
    residual capital continues to earn a return; payments are computed as a
    standard present-value annuity (PMT formula).

**Aldersforsikring** (lump sum)
    Paid as a one-off tax-free lump sum at the chosen retirement age.
    Amounts to the fraction of the pension balance not allocated to Livrente
    or Ratepension.

Tax treatment is **not** modelled here; see :mod:`penge.sim.tax` for the
personal-income and Topskat overlay.

Design rationale: ``docs/decisions/0028-sim-payout-model.md``.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

import pydantic

from penge.sim._decimal_utils import to_decimal as _to_decimal

__all__ = [
    "PayoutConfig",
    "PayoutError",
    "PayoutProjection",
    "compute_payout",
]

_TWO_DP = Decimal("0.01")
_SIX_DP = Decimal("0.000001")
_MILLION = Decimal("1000000")
_MIN_RETIREMENT_AGE = 60
_MIN_RATEPENSION_YEARS = 10
_MAX_RATEPENSION_YEARS = 30


class PayoutError(Exception):
    """Raised when the payout configuration is internally inconsistent."""


class PayoutConfig(pydantic.BaseModel):
    """Parameters that drive a single-entity decumulation computation.

    Args:
        entity: Identifier for the person/entity (e.g. ``"rouven"``).
        pension_balance_eur: Total pension account balance at retirement, in
            EUR.  Typically taken from :attr:`~penge.sim.cashflow.YearlyFlow
            .cumulative_pension_eur` at the chosen retirement year.
        retirement_age: Age at which payout begins.  Used for validation and
            documentation only — the annuity factor already embeds the
            provider's age-specific pricing.
        livrente_fraction: Share of the balance allocated to Livrente,
            expressed as a fraction of ``pension_balance_eur``
            (e.g. ``Decimal("0.70")`` for 70 %).
        ratepension_fraction: Share allocated to Ratepension
            (e.g. ``Decimal("0.25")`` for 25 %).  The remaining fraction
            ``1 - livrente_fraction - ratepension_fraction`` becomes the
            Aldersforsikring lump sum.
        ratepension_years: Drawdown period in years (10-30 inclusive).
        annuity_factor: Monthly gross payout per 1 000 000 units of
            Livrente capital, in the same currency as
            ``pension_balance_eur``.  Published annually by PFA /
            Finanstilsynet.  Because this is a pure *ratio*
            (monthly / capital), it is currency-neutral: use DKK-published
            values directly when the balance is held in EUR.
        growth_rate_during_payout: Annual nominal return earned by the
            Ratepension residual balance during drawdown (gross of tax,
            net of fees).  Default ``0`` ⟹ level monthly payments.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    entity: str
    pension_balance_eur: Decimal
    retirement_age: int
    livrente_fraction: Decimal
    ratepension_fraction: Decimal
    ratepension_years: int
    annuity_factor: Decimal
    growth_rate_during_payout: Decimal = Decimal("0")

    @pydantic.field_validator(
        "pension_balance_eur",
        "livrente_fraction",
        "ratepension_fraction",
        "annuity_factor",
        "growth_rate_during_payout",
        mode="before",
    )
    @classmethod
    def _coerce(cls, v: object) -> Decimal:
        return _to_decimal(v)

    @pydantic.model_validator(mode="after")
    def _validate(self) -> PayoutConfig:
        if self.pension_balance_eur < Decimal("0"):
            raise ValueError("pension_balance_eur must be >= 0")
        if self.retirement_age < _MIN_RETIREMENT_AGE:
            raise ValueError("retirement_age must be >= 60")
        if self.livrente_fraction < Decimal("0"):
            raise ValueError("livrente_fraction must be >= 0")
        if self.ratepension_fraction < Decimal("0"):
            raise ValueError("ratepension_fraction must be >= 0")
        total = self.livrente_fraction + self.ratepension_fraction
        if total > Decimal("1"):
            raise ValueError(f"livrente_fraction + ratepension_fraction must be <= 1, got {total}")
        if not (_MIN_RATEPENSION_YEARS <= self.ratepension_years <= _MAX_RATEPENSION_YEARS):
            raise ValueError("ratepension_years must be in [10, 30]")
        if self.annuity_factor <= Decimal("0"):
            raise ValueError("annuity_factor must be > 0")
        if self.growth_rate_during_payout <= Decimal("-1"):
            raise ValueError("growth_rate_during_payout must be > -1")
        return self


class PayoutProjection(pydantic.BaseModel):
    """Computed gross monthly payout for one entity at retirement.

    All amounts are in the same currency as
    :attr:`PayoutConfig.pension_balance_eur` (typically EUR).

    Args:
        config: The :class:`PayoutConfig` that produced this projection.
        livrente_capital_eur: Portion of the pension balance allocated to
            Livrente.
        ratepension_capital_eur: Portion allocated to Ratepension.
        aldersforsikring_lump_sum_eur: Remainder paid as a one-off tax-free
            lump sum at retirement.
        monthly_livrente_eur: Gross monthly Livrente payment (lifelong).
        monthly_ratepension_eur: Constant gross monthly Ratepension payment
            over the drawdown period.
        total_monthly_gross_eur: Sum of Livrente and Ratepension monthly
            payments (i.e. the recurrent gross monthly income in retirement,
            excluding the one-off Aldersforsikring).
    """

    model_config = pydantic.ConfigDict(frozen=True)

    config: PayoutConfig
    livrente_capital_eur: Decimal
    ratepension_capital_eur: Decimal
    aldersforsikring_lump_sum_eur: Decimal
    monthly_livrente_eur: Decimal
    monthly_ratepension_eur: Decimal
    total_monthly_gross_eur: Decimal


def _monthly_pmt(capital: Decimal, annual_rate: Decimal, n_months: int) -> Decimal:
    """Compute the level monthly payment for an amortising drawdown.

    Uses the standard PMT formula:
    ``PMT = P * r / (1 - (1 + r)^(-n))``
    where ``r`` is the monthly rate derived from ``annual_rate``.

    When ``annual_rate`` is zero the formula degenerates to ``P / n``.

    Args:
        capital: Starting balance to draw down.
        annual_rate: Annual nominal growth rate on the residual balance
            (e.g. ``Decimal("0.05")`` for 5 %).  Must be > -1.
        n_months: Total number of monthly payments.

    Returns:
        The constant monthly gross payment, rounded to 2 decimal places.
    """
    if capital == Decimal("0"):
        return Decimal("0")
    if annual_rate == Decimal("0"):
        return (capital / Decimal(n_months)).quantize(_TWO_DP, rounding=ROUND_HALF_EVEN)

    # Monthly rate: (1 + annual)^(1/12) - 1.
    # Decimal doesn't support fractional exponents; we convert to float for this
    # single intermediate step and then return to Decimal.  The precision loss
    # (< 1e-14 relative) is negligible for a planning projection.
    r_float = float(annual_rate + Decimal("1")) ** (1.0 / 12) - 1.0
    r = Decimal(str(r_float)).quantize(_SIX_DP, rounding=ROUND_HALF_EVEN)

    # PMT = P * r / (1 - (1 + r)^(-n))
    one_plus_r = Decimal("1") + r
    discount = Decimal("1") - one_plus_r ** (-n_months)
    pmt = capital * r / discount
    return pmt.quantize(_TWO_DP, rounding=ROUND_HALF_EVEN)


def compute_payout(config: PayoutConfig) -> PayoutProjection:
    """Compute gross monthly retirement income for a single entity.

    **Livrente** monthly amount::

        monthly_livrente = livrente_capital * (annuity_factor / 1_000_000)

    Because the annuity factor is a pure ratio (monthly/capital) published in
    whatever currency the provider uses, it is currency-neutral; using a
    DKK-denominated factor with an EUR balance is mathematically identical —
    both numerator and denominator are scaled by the same constant.

    **Ratepension** monthly amount: standard PMT over ``ratepension_years * 12``
    months at the monthly rate derived from ``growth_rate_during_payout``.

    Args:
        config: Validated :class:`PayoutConfig`.

    Returns:
        :class:`PayoutProjection` with all capital splits and monthly amounts.

    Raises:
        PayoutError: Never raised by the current implementation; reserved for
            future validation that spans multiple configs (e.g. household
            total).
    """
    balance = config.pension_balance_eur

    livrente_capital = (balance * config.livrente_fraction).quantize(
        _TWO_DP, rounding=ROUND_HALF_EVEN
    )
    ratepension_capital = (balance * config.ratepension_fraction).quantize(
        _TWO_DP, rounding=ROUND_HALF_EVEN
    )
    aldersforsikring = (balance - livrente_capital - ratepension_capital).quantize(
        _TWO_DP, rounding=ROUND_HALF_EVEN
    )

    monthly_livrente = (livrente_capital * config.annuity_factor / _MILLION).quantize(
        _TWO_DP, rounding=ROUND_HALF_EVEN
    )
    monthly_ratepension = _monthly_pmt(
        ratepension_capital,
        config.growth_rate_during_payout,
        config.ratepension_years * 12,
    )

    total_monthly = (monthly_livrente + monthly_ratepension).quantize(
        _TWO_DP, rounding=ROUND_HALF_EVEN
    )

    return PayoutProjection(
        config=config,
        livrente_capital_eur=livrente_capital,
        ratepension_capital_eur=ratepension_capital,
        aldersforsikring_lump_sum_eur=aldersforsikring,
        monthly_livrente_eur=monthly_livrente,
        monthly_ratepension_eur=monthly_ratepension,
        total_monthly_gross_eur=total_monthly,
    )
