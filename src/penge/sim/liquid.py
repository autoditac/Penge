"""Liquid portfolio simulation — ASK and frie midler, tax-aware.

This module models the year-by-year dynamics of a Danish liquid investment
portfolio split across one or more accounts with different tax treatment.

## Account types and tax regimes

**Aktiesparekonto (ASK)**
  Flat **17 %** mark-to-market (lager) tax on annual gains.  Annual deposits
  are capped by SKAT's cumulative lifetime deposit limit; see
  :data:`penge.tax.aktiesparekonto.ASK_DEPOSIT_CAPS` for the per-year
  confirmed table.  The simulation uses :data:`_ASK_DEPOSIT_CAPS_EXTENDED`
  (an extension of that table with estimates for future years) via
  :func:`ask_cap_for_year`.
  All instruments inside ASK are taxed at 17 % regardless of instrument type.

**Frie midler — Lagerbeskatning**
  Annual mark-to-market tax at progressive Aktieindkomst rates:

  * **27 %** on gains up to the per-year threshold (2024: 61 900 DKK,
    indexed annually — see :data:`AKTIEINDKOMST_THRESHOLDS` / use
    :func:`threshold_for_year` to look up the value for a given year).
  * **42 %** on gains above the threshold.

  Applies to instruments on the ABIS list (e.g. most Irish-domiciled UCITS ETFs).

**Frie midler — Realisationsbeskatning**
  Capital gains deferred until actual sale (gennemsnitsmetoden / average-cost
  method).  Dividends from *udloddende* funds are distributed annually and taxed
  as Aktieindkomst (27 %/42 %) in the year received.  Cost basis is tracked so
  the correct gain fraction can be applied at each sale during the bridge phase.

## Key improvements over a naive "flat effective rate" approach

1. **Progressive bracket** computed from actual annual gain magnitude, not a
   fixed rate.  For a growing depot, the 27 % bracket is exhausted quickly:
   at ~625 000 DKK the 9.88 % annual gain already exceeds 61 900 DKK.
2. **ASK capped routing**: contributions fill ASK first (cheaper 17 % tax)
   up to the per-year cumulative cap; once the cap is reached, additional
   contributions are *not* deposited into ASK (the caller is responsible
   for routing the overflow to a frie-midler depot — :func:`project_liquid`
   does *not* implicitly move it).
3. **Annual expense ratio (ÅOP)** deducted from gross return before tax, so the
   net-return base is correct for both account types.
4. **Realisation regime**: only dividend yield taxed annually; capital gain
   deferred.  Cost basis tracked for each account so the exact gain fraction
   (and therefore tax per DKK withdrawn) is known at drawdown time.
5. **Bridge decumulation PMT** found via binary search over a full monthly
   simulation, not a closed-form formula with a flat assumed net rate.  Lager
   mark-to-market tax is deducted annually (December) during drawdown; Realisation
   tax is deducted proportionally on each monthly withdrawal.

## Design notes

* All monetary inputs and outputs are in **DKK**.
* Tax payment source matters for the accumulation simulation:
  - ``TaxSource.EXTERNAL``: Lager tax paid from salary or outside savings; the
    depot balance grows at the full net rate — maximises compound growth.
  - ``TaxSource.DEPOT``: tax deducted from the depot balance, forcing a notional
    partial liquidation.  This is the only option during the bridge phase
    (no external income to pay from).
* The AKTIEINDKOMST_THRESHOLDS table must be updated each year when SKAT
  publishes its satser.  Projections for future years fall back to the last
  known threshold — a conservative choice because it classifies more gain at
  42 % than may actually apply.
* ÅOP drag is applied symmetrically: it reduces the net return base before tax.
  For accumulation-class funds (akkumulerende) this reflects the daily NAV drag.
  For distributing funds (udloddende), the ÅOP drag is separate from the
  dividend yield — see the Realisation path in :func:`project_liquid`.

References:
  * ``docs/tax/dk.md`` — tax law notes
  * ``penge.tax.aktiesparekonto`` — ASK rate constant and deposit-cap table
  * ``penge.tax.lager`` — mark-to-market formula used by the real tax calculator
  * Issues #134 (ASK), #135 (Lager vs Realisation), #136 (ÅOP comparison),
    #137 (routing), #138 (fund comparison), #139 (bridge decumulation)
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import Final, Literal

import pydantic

from penge.tax.aktiesparekonto import ASK_DEPOSIT_CAPS, ASK_RATE

__all__ = [
    "AKTIEINDKOMST_HIGH_RATE",
    "AKTIEINDKOMST_LOW_RATE",
    "AKTIEINDKOMST_THRESHOLDS",
    "AccountType",
    "BridgeConfig",
    "BridgeResult",
    "FundProfile",
    "LiquidDepotConfig",
    "LiquidDepotError",
    "LiquidProjection",
    "TaxRegime",
    "TaxSource",
    "YearlyLiquidFlow",
    "ask_cap_for_year",
    "compare_liquid_strategies",
    "compute_aktieindkomst_tax",
    "compute_bridge_pmt",
    "project_liquid",
    "threshold_for_year",
]

_DP2 = Decimal("0.01")


def _to_decimal(v: object) -> Decimal:
    """Coerce *v* to a finite Decimal or raise ``ValueError``.

    Mirrors :func:`penge.sim.cashflow._to_decimal` so liquid-depot config
    validation rejects ``NaN``/``Infinity`` and surfaces a clear error
    instead of leaking :class:`decimal.InvalidOperation`.
    """
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"cannot convert {v!r} to Decimal") from exc
    if not d.is_finite():
        raise ValueError(f"value must be finite, got {v!r}")
    return d


# ──────────────────────────────────────────────────────────────────────────────
# Tax-rate constants and annual tables
# ──────────────────────────────────────────────────────────────────────────────

AKTIEINDKOMST_LOW_RATE: Final = Decimal("0.27")
AKTIEINDKOMST_HIGH_RATE: Final = Decimal("0.42")

AKTIEINDKOMST_THRESHOLDS: Final[Mapping[int, Decimal]] = {
    # SKAT publishes the per-year threshold in its annual satser.
    # Source: skat.dk (confirmed values).
    2024: Decimal("61900"),
    # 2025: estimated at 67 500 DKK based on wage-index regulation (+9 %).
    # Update to the confirmed value when SKAT publishes satser for 2025.
    2025: Decimal("67500"),
    # 2026: estimated at 70 700 DKK (≈+4.7 % from 2025, matching historical indexing).
    # Update to the confirmed value when SKAT publishes satser for 2026.
    2026: Decimal("70700"),
}
"""Progressive aktieindkomst threshold per person (DKK), indexed annually.

Gains up to the threshold are taxed at 27 %; gains above at 42 %.  The
threshold applies at the *household* level for married couples (2 * threshold).
Values marked as estimated must be replaced with the SKAT-published figure.

Update this mapping each November/December for the following year.
"""

# Extend the ASK deposit-cap table for 2026 (estimated from wage-index).
# The confirmed 2025 cap is 142 500 DKK.  Estimated 2026: 148 000 DKK (≈+3.9 %).
# Replace with the SKAT-published value when available.
_ASK_DEPOSIT_CAPS_EXTENDED: Final[Mapping[int, Decimal]] = {
    **ASK_DEPOSIT_CAPS,  # 2019-2025 confirmed
    2026: Decimal("148000"),  # estimated; update from SKAT satser
}


class LiquidDepotError(Exception):
    """Raised on invalid liquid depot configuration or calculation error."""


# ──────────────────────────────────────────────────────────────────────────────
# Enumerations
# ──────────────────────────────────────────────────────────────────────────────


class AccountType(str):
    """Values for :attr:`LiquidDepotConfig.account_type`."""

    ASK = "ask"
    FRIE_MIDLER = "frie_midler"


class TaxRegime(str):
    """Values for :attr:`LiquidDepotConfig.tax_regime`."""

    LAGER = "lager"
    REALISATION = "realisation"


class TaxSource(str):
    """Where the annual Lager tax is sourced from.

    ``EXTERNAL``: paid from salary or other outside savings — the depot
    balance is unaffected, maximising compound growth.

    ``DEPOT``: tax deducted from the depot balance itself (forced notional
    sell).  Required when there is no external income, e.g. during the bridge
    phase.
    """

    EXTERNAL = "external"
    DEPOT = "depot"


# ──────────────────────────────────────────────────────────────────────────────
# Helper: progressive tax computation
# ──────────────────────────────────────────────────────────────────────────────


def _q(v: Decimal) -> Decimal:
    return v.quantize(_DP2, rounding=ROUND_HALF_EVEN)


def compute_aktieindkomst_tax(
    *,
    gain_dkk: Decimal,
    threshold_dkk: Decimal,
    low_rate: Decimal = AKTIEINDKOMST_LOW_RATE,
    high_rate: Decimal = AKTIEINDKOMST_HIGH_RATE,
) -> Decimal:
    """Compute progressive Aktieindkomst tax on a capital gain.

    Applies the two-bracket schedule:

    * ``gain ≤ threshold_dkk``: taxed at ``low_rate`` (27 %)
    * ``gain > threshold_dkk``: excess taxed at ``high_rate`` (42 %)

    Losses (negative gains) return zero.  This module does **not** track
    aktieindkomst loss carry-forward across years — historical losses are
    simply dropped.  Lager regimes in this module are projection-only and
    are not used to file taxes; if loss carry-forward becomes material,
    the caller must implement it on top of this primitive.

    Args:
        gain_dkk: Annual taxable gain in DKK.  Negative values return zero.
        threshold_dkk: Per-person threshold for the current tax year.  Use
            :func:`threshold_for_year` to look up the correct value.
        low_rate: Tax rate below the threshold.  Default 27 %.
        high_rate: Tax rate above the threshold.  Default 42 %.

    Returns:
        Tax amount in DKK, quantised to 2 decimal places.
    """
    if gain_dkk <= Decimal("0"):
        return Decimal("0")
    low_portion = min(gain_dkk, threshold_dkk)
    high_portion = max(gain_dkk - threshold_dkk, Decimal("0"))
    tax = low_portion * low_rate + high_portion * high_rate
    return _q(tax)


def threshold_for_year(year: int) -> Decimal:
    """Return the best available aktieindkomst threshold for *year* (DKK, per person).

    Returns the exact value if the year is in :data:`AKTIEINDKOMST_THRESHOLDS`.
    For years *after* the table, falls back to the last known year's value
    (callers should treat such projections as ±5 % uncertain on the bracket).
    For years *before* the earliest configured year, raises rather than
    silently using a future threshold — historical projections should be
    explicit about the year they cover.

    Args:
        year: Calendar year for the threshold lookup.

    Returns:
        Per-person aktieindkomst threshold in DKK.

    Raises:
        LiquidDepotError: If *year* is earlier than the earliest year in
            :data:`AKTIEINDKOMST_THRESHOLDS`.
    """
    if year in AKTIEINDKOMST_THRESHOLDS:
        return AKTIEINDKOMST_THRESHOLDS[year]
    first = min(AKTIEINDKOMST_THRESHOLDS)
    if year < first:
        raise LiquidDepotError(
            f"no aktieindkomst threshold available for year {year} "
            f"(earliest configured year is {first})"
        )
    last = max(AKTIEINDKOMST_THRESHOLDS)
    return AKTIEINDKOMST_THRESHOLDS[last]


def ask_cap_for_year(year: int) -> Decimal:
    """Return the ASK cumulative deposit cap for *year* (DKK).

    Uses :data:`_ASK_DEPOSIT_CAPS_EXTENDED` which extends the confirmed
    :data:`penge.tax.aktiesparekonto.ASK_DEPOSIT_CAPS` table with estimates
    for future years.  For years beyond the last configured year the
    function falls back to the last known cap (conservative for planning —
    no implicit increase).  For years before the earliest configured year
    it raises :class:`LiquidDepotError`.

    Raises:
        LiquidDepotError: If *year* is earlier than the earliest configured
            year (no historical cap available).
    """
    if year in _ASK_DEPOSIT_CAPS_EXTENDED:
        return _ASK_DEPOSIT_CAPS_EXTENDED[year]
    last = max(_ASK_DEPOSIT_CAPS_EXTENDED)
    if year > last:
        return _ASK_DEPOSIT_CAPS_EXTENDED[last]
    raise LiquidDepotError(f"no ASK deposit cap available for year {year}")


# ──────────────────────────────────────────────────────────────────────────────
# Configuration models
# ──────────────────────────────────────────────────────────────────────────────


class LiquidDepotConfig(pydantic.BaseModel):
    """Configuration for one liquid investment account (ASK or frie midler).

    Args:
        account_id: Human-readable label (e.g. ``"nordnet-ask"``).
        account_type: ``"ask"`` or ``"frie_midler"``.
        tax_regime: ``"lager"`` (mark-to-market annual tax) or
            ``"realisation"`` (tax deferred to sale).  ASK always uses
            lager; frie midler can be either.
        opening_balance_dkk: Current account value in DKK at the start
            of the projection.  Must be ≥ 0.
        ask_lifetime_deposits_dkk: For ASK only — cumulative **net**
            deposits ever made into the account (DKK).  This is the
            SKAT-defined accounting basis for the ASK deposit cap:
            withdrawals reduce this running total (see
            :func:`penge.tax.aktiesparekonto.check_deposit_cap`).  The
            accumulation projection in this module does **not** model
            intra-horizon withdrawals from ASK, so once seeded the value
            only grows (capped at the per-year limit returned by
            :func:`ask_cap_for_year`).  If you later add withdrawal
            modelling to ASK accumulation, the per-year tracker must
            decrement on withdrawal to preserve cap headroom.  Ignored
            for frie midler.
        annual_contribution_dkk: Amount added to this account per year
            (DKK at base-year prices, not inflation-adjusted).
        gross_annual_return_rate: Expected **total** annual return rate
            *before* ÅOP, **including any dividend yield**, e.g.
            ``Decimal("0.10")`` for 10 % total return.  For
            *realisationsbeskatning* (udloddende) funds the realisation
            path internally splits this total into a dividend component
            (``opening_balance * annual_dividend_yield``) and a capital-
            appreciation component (``gross_return - dividend_gross``);
            do **not** supply price-only return here in addition to a
            non-zero ``annual_dividend_yield`` or dividends will be
            double-counted.
        annual_expense_ratio: Total annual fund cost (ÅOP), e.g.
            ``Decimal("0.0012")`` for 0.12 % (iShares ETF) or
            ``Decimal("0.0049")`` for 0.49 % (Sparinvest fond).
        annual_dividend_yield: For *realisationsbeskatning* funds
            (*udloddende*): fraction of the balance distributed as
            dividend each year (taxed annually as Aktieindkomst).
            Use ``Decimal("0")`` for accumulating (akkumulerende)
            instruments.
        tax_source: Whether Lager tax is paid from external income
            (``"external"``) or from the depot balance (``"depot"``).
            External is optimal during accumulation (full compounding);
            depot is typically unavoidable during the bridge phase.
        aktieindkomst_threshold_dkk: Per-person progressive bracket
            threshold to use for this account's tax calculations.  Call
            :func:`threshold_for_year` with the base year to get the
            correct value.  For projections spanning multiple years the
            threshold is held constant — update :data:`AKTIEINDKOMST_THRESHOLDS`
            for more precise long-horizon results.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    account_id: str
    account_type: Literal["ask", "frie_midler"]
    tax_regime: Literal["lager", "realisation"]
    opening_balance_dkk: Decimal
    ask_lifetime_deposits_dkk: Decimal = Decimal("0")
    annual_contribution_dkk: Decimal
    gross_annual_return_rate: Decimal
    annual_expense_ratio: Decimal
    annual_dividend_yield: Decimal = Decimal("0")
    tax_source: Literal["external", "depot"] = "external"
    aktieindkomst_threshold_dkk: Decimal = Decimal("61900")

    @pydantic.field_validator(
        "opening_balance_dkk",
        "ask_lifetime_deposits_dkk",
        "annual_contribution_dkk",
        "gross_annual_return_rate",
        "annual_expense_ratio",
        "annual_dividend_yield",
        "aktieindkomst_threshold_dkk",
        mode="before",
    )
    @classmethod
    def _coerce(cls, v: object) -> Decimal:
        return _to_decimal(v)

    @pydantic.model_validator(mode="after")
    def _validate(self) -> LiquidDepotConfig:
        if self.opening_balance_dkk < Decimal("0"):
            raise ValueError("opening_balance_dkk must be ≥ 0")
        if self.annual_contribution_dkk < Decimal("0"):
            raise ValueError("annual_contribution_dkk must be ≥ 0")
        if not (Decimal("-0.5") <= self.gross_annual_return_rate <= Decimal("2")):
            raise ValueError("gross_annual_return_rate must be in [-0.5, 2.0]")
        if not (Decimal("0") <= self.annual_expense_ratio < Decimal("1")):
            raise ValueError("annual_expense_ratio must be in [0, 1)")
        if not (Decimal("0") <= self.annual_dividend_yield < Decimal("1")):
            raise ValueError("annual_dividend_yield must be in [0, 1)")
        if self.account_type == "ask" and self.tax_regime != "lager":
            raise ValueError("ASK accounts always use lager tax regime")
        if self.account_type == "ask" and self.annual_dividend_yield != Decimal("0"):
            raise ValueError(
                "annual_dividend_yield must be 0 for ASK accounts (dividend yield "
                "is only relevant for Realisationsbeskatning frie midler accounts)"
            )
        if self.ask_lifetime_deposits_dkk < Decimal("0"):
            raise ValueError("ask_lifetime_deposits_dkk must be ≥ 0")
        if self.aktieindkomst_threshold_dkk <= Decimal("0"):
            raise ValueError("aktieindkomst_threshold_dkk must be > 0")
        net_return = self.gross_annual_return_rate - self.annual_expense_ratio
        if net_return <= Decimal("-1"):
            raise ValueError(
                "gross_annual_return_rate - annual_expense_ratio must be > -1 "
                "(net return would liquidate the depot in one year)"
            )
        return self


class YearlyLiquidFlow(pydantic.BaseModel):
    """Computed cashflow for one liquid depot account in one calendar year.

    Args:
        year: Calendar year.
        account_id: Account identifier from the config.
        opening_balance_dkk: Balance at the start of the year (DKK).
        annual_contribution_dkk: Amount actually deposited during the year
            (DKK).  For ASK accounts this is the contribution after the
            cumulative deposit-cap clamp — any portion that did not fit
            is surfaced in ``contribution_overflow_dkk``.  For frie midler
            this always equals the configured ``annual_contribution_dkk``.
        contribution_overflow_dkk: Amount the caller asked to contribute
            this year that exceeded the ASK cap and was therefore *not*
            deposited (DKK).  Zero for frie midler.  This value is
            **year-specific** — it cannot be summed and re-injected as a
            constant annual contribution because :func:`project_liquid`
            only models a single constant ``annual_contribution_dkk``.
            Callers that want to route overflow into a frie-midler depot
            should run two projections in lock-step (year-by-year),
            feeding each year's overflow into a separate frie-midler
            cashflow for that year — or use a higher-level multi-account
            engine.
        gross_return_dkk: Return on the opening balance at the net-of-ÅOP
            rate (``opening_balance * (gross_rate - ÅOP)``), in DKK.
        taxable_gain_dkk: The portion of the gain subject to annual tax.
            For *lager*: equals ``gross_return_dkk``.
            For *realisation*: equals the dividend portion only
            (``opening_balance * dividend_yield``).
        tax_due_dkk: Annual tax liability payable to SKAT.  Non-zero whenever
            there is a taxable gain, regardless of ``tax_source``.  It is the
            full gross liability — how the tax is *funded* is recorded
            separately in ``tax_deducted_from_depot_dkk``.
        tax_deducted_from_depot_dkk: Portion of ``tax_due_dkk`` actually
            removed from the depot balance this year.  Zero when
            ``tax_source == "external"`` (tax is paid from outside the depot);
            equals ``tax_due_dkk`` otherwise.
        dividend_received_net_dkk: For *realisation* accounts — dividend paid
            out and reinvested into the depot.  When
            ``tax_source == "depot"`` this is ``dividend_gross - tax_due``
            (the tax is taken at the source); when
            ``tax_source == "external"`` the full ``dividend_gross`` is
            reinvested because the tax is settled from outside funds.
            Zero for *lager*.
        closing_balance_dkk: Balance at end of year after return, contribution,
            dividends, and any depot-deducted tax.
        cost_basis_dkk: For *realisation* accounts — cumulative amount
            invested (opening balance + all contributions + all reinvested net
            dividends).  Used to compute the gain fraction at drawdown.
            Equals ``closing_balance_dkk`` for *lager* (no deferred gain).
        cumulative_ask_deposits_dkk: Running total of net deposits into an ASK
            account (DKK), used for cap enforcement.  Zero for frie midler.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    year: int
    account_id: str
    opening_balance_dkk: Decimal
    annual_contribution_dkk: Decimal
    contribution_overflow_dkk: Decimal = Decimal("0")
    gross_return_dkk: Decimal
    taxable_gain_dkk: Decimal
    tax_due_dkk: Decimal
    tax_deducted_from_depot_dkk: Decimal
    dividend_received_net_dkk: Decimal
    closing_balance_dkk: Decimal
    cost_basis_dkk: Decimal
    cumulative_ask_deposits_dkk: Decimal


class LiquidProjection(pydantic.BaseModel):
    """Full output of :func:`project_liquid`.

    Args:
        config: The configuration that produced this projection.
        flows: Per-year flows in ascending year order.
        terminal_gain_fraction: At the end of the horizon, what fraction of
            the terminal balance is unrealised capital gain (relevant for
            :func:`compute_bridge_pmt` with the realisation regime).
    """

    model_config = pydantic.ConfigDict(frozen=True)

    config: LiquidDepotConfig
    flows: tuple[YearlyLiquidFlow, ...]
    terminal_gain_fraction: Decimal

    def terminal_balance_dkk(self) -> Decimal:
        """Balance at the end of the projection horizon."""
        if not self.flows:
            return self.config.opening_balance_dkk
        return self.flows[-1].closing_balance_dkk

    def total_tax_paid_dkk(self) -> Decimal:
        """Sum of all tax paid from the depot balance during the projection."""
        return sum((f.tax_deducted_from_depot_dkk for f in self.flows), Decimal("0"))

    def total_tax_due_dkk(self) -> Decimal:
        """Sum of all tax due (both depot-deducted and externally paid)."""
        return sum((f.tax_due_dkk for f in self.flows), Decimal("0"))

    def total_contributions_dkk(self) -> Decimal:
        """Sum of contributions actually deposited across all years.

        For ASK accounts this excludes any contribution overflow that was
        capped (and dropped) by the cumulative deposit limit.  This is the
        amount of new money that entered the depot — it does *not* include
        the opening balance.
        """
        return sum((f.annual_contribution_dkk for f in self.flows), Decimal("0"))


# ──────────────────────────────────────────────────────────────────────────────
# Core projection function
# ──────────────────────────────────────────────────────────────────────────────


def _compute_annual_tax(
    config: LiquidDepotConfig,
    opening_balance: Decimal,
    gross_return: Decimal,
) -> tuple[Decimal, Decimal]:
    """Return (taxable_gain, tax_due) for one annual step."""
    if config.account_type == "ask":
        taxable_gain = gross_return
        tax_due = _q(taxable_gain * ASK_RATE) if taxable_gain > Decimal("0") else Decimal("0")
    elif config.tax_regime == "lager":
        taxable_gain = gross_return
        tax_due = compute_aktieindkomst_tax(
            gain_dkk=taxable_gain,
            threshold_dkk=config.aktieindkomst_threshold_dkk,
        )
    else:
        # Realisation: only dividend portion taxed annually
        dividend_gross = _q(opening_balance * config.annual_dividend_yield)
        taxable_gain = dividend_gross
        tax_due = compute_aktieindkomst_tax(
            gain_dkk=dividend_gross,
            threshold_dkk=config.aktieindkomst_threshold_dkk,
        )
    return taxable_gain, tax_due


def _apply_ask_cap(
    config: LiquidDepotConfig,
    year: int,
    contribution: Decimal,
    cumulative_ask_deposits: Decimal,
) -> tuple[Decimal, Decimal]:
    """Return (capped_contribution, updated_cumulative_deposits) for ASK."""
    cap = ask_cap_for_year(year)
    max_deposit = cap - cumulative_ask_deposits
    contribution = Decimal("0") if max_deposit <= Decimal("0") else min(contribution, max_deposit)
    return contribution, _q(cumulative_ask_deposits + contribution)


def _closing_balance_and_basis(
    config: LiquidDepotConfig,
    opening_balance: Decimal,
    gross_return: Decimal,
    tax_deducted: Decimal,
    dividend_gross: Decimal,
    dividend_net: Decimal,
    contribution: Decimal,
    cost_basis: Decimal,
) -> tuple[Decimal, Decimal]:
    """Return (closing_balance, updated_cost_basis)."""
    if config.tax_regime == "realisation" and config.account_type == "frie_midler":
        # Capital appreciation = gross_return minus the distributed dividend.
        # dividend_net is already net of dividend tax, so we must NOT also
        # subtract tax_deducted here for tax_source == "depot" — that would
        # double-debit the dividend tax against the depot.  The full
        # liability is reported via tax_due / total_tax_due_dkk; the
        # balance impact lives entirely in dividend_net.
        capital_appreciation = _q(gross_return - dividend_gross)
        closing = _q(opening_balance + capital_appreciation + dividend_net + contribution)
        new_cost_basis = _q(cost_basis + contribution + dividend_net)
    else:
        # Lager: full gross return, minus any depot-deducted tax
        closing = _q(opening_balance + gross_return - tax_deducted + contribution)
        # For lager, cost basis equals balance (no deferred gain)
        new_cost_basis = closing
    return closing, new_cost_basis


def project_liquid(
    config: LiquidDepotConfig,
    *,
    base_year: int,
    horizon_years: int,
) -> LiquidProjection:
    """Run a year-by-year simulation of a single liquid depot account.

    For each year the following sequence is applied:

    1. **Gross return** is earned: ``opening_balance * (gross_rate - AOP)``.
    2. **Tax is computed** based on the account type and regime:
       - *ASK lager*: flat 17 % on the gross return.
       - *Frie midler lager*: progressive 27 %/42 % on the gross return.
       - *Frie midler realisation*: tax on dividend portion only; capital
         gain accrues in the cost-basis "deferred gain" for later.
    3. **Dividend is paid** (realisation regime only): net-of-tax dividend
       is credited to the balance and added to the cost basis.
    4. **Contribution** is added to the balance (and to the cost basis for
       realisation accounts).  For ASK accounts the contribution is limited
       by the remaining cap; any excess is **not silently dropped** — it is
       surfaced on each :class:`YearlyLiquidFlow` as
       ``contribution_overflow_dkk`` so the caller can route the overflow
       (e.g. to a separate frie-midler depot).  See the
       :class:`YearlyLiquidFlow` docstring for the recommended year-by-year
       routing pattern.
    5. **Closing balance** is computed:
       - *Lager* regime: balance = opening + return + contribution - tax
         (the entire annual gain is taxed; ``tax_source == "depot"``
         deducts ``tax`` from the depot, while ``"external"`` leaves the
         depot whole and reports zero ``tax_deducted_from_depot_dkk``).
       - *Realisation* regime: balance = opening + capital_appreciation
         + net_dividend + contribution.  The dividend tax is already
         embedded in ``net_dividend`` (gross when ``tax_source ==
         "external"``, gross - tax when ``"depot"``); the deferred
         capital gain is *not* taxed here — it accrues against the
         cost basis until the bridge phase.

    Args:
        config: Account configuration.
        base_year: Year before the first projected year.
        horizon_years: Number of years to project.

    Returns:
        :class:`LiquidProjection` with one :class:`YearlyLiquidFlow` per year.

    Raises:
        LiquidDepotError: If ``horizon_years`` is less than 1, or if the
            account is ASK and ``config.ask_lifetime_deposits_dkk`` already
            exceeds the cap that applies to the first projected year
            (i.e. the configuration is impossible — SKAT could not have
            allowed those deposits historically).
    """
    if horizon_years < 1:
        raise LiquidDepotError("horizon_years must be >= 1")

    if config.account_type == "ask":
        first_year = base_year + 1
        applicable_cap = ask_cap_for_year(first_year)
        if config.ask_lifetime_deposits_dkk > applicable_cap:
            raise LiquidDepotError(
                f"ask_lifetime_deposits_dkk ({config.ask_lifetime_deposits_dkk}) "
                f"exceeds the {first_year} ASK cap ({applicable_cap}); "
                "the seeded cumulative deposits cannot exceed what SKAT "
                "would have allowed historically. Check the configuration."
            )

    net_return_rate = config.gross_annual_return_rate - config.annual_expense_ratio
    balance = config.opening_balance_dkk
    # cost_basis tracks total cash invested for realisation accounts.
    # For lager accounts cost_basis == balance (no deferred gain).
    cost_basis = config.opening_balance_dkk
    cumulative_ask_deposits = config.ask_lifetime_deposits_dkk

    flows: list[YearlyLiquidFlow] = []

    for t in range(1, horizon_years + 1):
        year = base_year + t
        opening_balance = balance

        gross_return = _q(opening_balance * net_return_rate)
        taxable_gain, tax_due = _compute_annual_tax(config, opening_balance, gross_return)
        tax_deducted = tax_due if config.tax_source == "depot" else Decimal("0")

        is_realisation_frie = (
            config.tax_regime == "realisation" and config.account_type == "frie_midler"
        )
        if is_realisation_frie:
            dividend_gross = _q(opening_balance * config.annual_dividend_yield)
            # The dividend is paid out of the gross return.  Which net
            # amount reinvests into the depot depends on tax_source:
            #   - "depot":    SKAT takes its cut directly from the dividend,
            #                 only the net flows back into the depot.
            #   - "external": the depot reinvests the full gross dividend;
            #                 the tax is settled from outside funds.
            # In either case `tax_due_dkk` reports the full liability and
            # `tax_deducted_from_depot_dkk` reports the actual depot impact.
            if config.tax_source == "depot":
                dividend_net = _q(dividend_gross - tax_due)
            else:
                dividend_net = dividend_gross
        else:
            dividend_gross = Decimal("0")
            dividend_net = Decimal("0")

        contribution = config.annual_contribution_dkk
        contribution_overflow = Decimal("0")
        if config.account_type == "ask":
            uncapped_contribution = contribution
            contribution, cumulative_ask_deposits = _apply_ask_cap(
                config, year, contribution, cumulative_ask_deposits
            )
            contribution_overflow = _q(uncapped_contribution - contribution)

        balance, cost_basis = _closing_balance_and_basis(
            config,
            opening_balance,
            gross_return,
            tax_deducted,
            dividend_gross,
            dividend_net,
            contribution,
            cost_basis,
        )

        flows.append(
            YearlyLiquidFlow(
                year=year,
                account_id=config.account_id,
                opening_balance_dkk=opening_balance,
                annual_contribution_dkk=contribution,
                contribution_overflow_dkk=contribution_overflow,
                gross_return_dkk=gross_return,
                taxable_gain_dkk=taxable_gain,
                tax_due_dkk=tax_due,
                tax_deducted_from_depot_dkk=tax_deducted,
                dividend_received_net_dkk=dividend_net,
                closing_balance_dkk=balance,
                cost_basis_dkk=cost_basis,
                cumulative_ask_deposits_dkk=cumulative_ask_deposits,
            )
        )

    if config.tax_regime == "realisation" and balance > Decimal("0"):
        # Keep higher precision than money: this ratio is later multiplied
        # by withdrawal amounts to compute the taxable gain portion, so
        # rounding to 0.01 here would introduce ~1 % error in withdrawal
        # tax.  Quantize to 8 decimal places — well below the precision of
        # any downstream Decimal money operation.
        terminal_gain_fraction = (
            max(balance - cost_basis, Decimal("0")) / balance
        ).quantize(Decimal("0.00000001"))
    else:
        terminal_gain_fraction = Decimal("0")

    return LiquidProjection(
        config=config,
        flows=tuple(flows),
        terminal_gain_fraction=terminal_gain_fraction,
    )


# -----------------------------------------------------------------------------
# Bridge / decumulation
# -----------------------------------------------------------------------------


class BridgeConfig(pydantic.BaseModel):
    """Configuration for the bridge (decumulation) phase.

    Args:
        starting_balance_dkk: Portfolio value at the start of the bridge.
            For a realistic projection, this is the
            :meth:`LiquidProjection.terminal_balance_dkk` of the
            accumulation phase.
        cost_basis_dkk: Total amount invested (DKK) — used to compute the
            gain fraction for Realisationsbeskatning.  For a Lager account
            this should equal ``starting_balance_dkk`` (all gains taxed).
        horizon_months: Number of months over which to deplete the portfolio.
            Typically 120 (10 years) for a bridge to a pension start.
        gross_annual_return_rate: Expected **total** gross return during
            drawdown (same assumption as accumulation or more conservative),
            **including any dividend yield**.  Do not pass price-only
            return together with a non-zero ``annual_dividend_yield``.
        annual_expense_ratio: Fund ÅOP during drawdown.
        account_type: ``"ask"`` or ``"frie_midler"``.
        tax_regime: ``"lager"`` or ``"realisation"``.
        aktieindkomst_threshold_dkk: Per-person tax threshold.  Use
            :func:`threshold_for_year` for the bridge start year.

    .. note::

       The bridge simulator currently models **akkumulerende** funds
       only (no dividend distributions during decumulation).  Modelling
       ``tax_regime == "realisation"`` with a non-zero dividend yield
       during the bridge — where dividends would create their own
       annual aktieindkomst tax line on top of the gain-fraction tax on
       withdrawals — is not supported and is rejected at validation
       time.  Construct the bridge from a realisation account by either
       (a) using an akkumulerende fund (dividend_yield == 0) or
       (b) modelling the dividend cashflow separately at the household
       cashflow level.  See issue #158 for the follow-up.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    starting_balance_dkk: Decimal
    cost_basis_dkk: Decimal
    horizon_months: int
    gross_annual_return_rate: Decimal
    annual_expense_ratio: Decimal
    account_type: Literal["ask", "frie_midler"]
    tax_regime: Literal["lager", "realisation"]
    aktieindkomst_threshold_dkk: Decimal = Decimal("61900")
    annual_dividend_yield: Decimal = Decimal("0")

    @pydantic.field_validator(
        "starting_balance_dkk",
        "cost_basis_dkk",
        "gross_annual_return_rate",
        "annual_expense_ratio",
        "aktieindkomst_threshold_dkk",
        "annual_dividend_yield",
        mode="before",
    )
    @classmethod
    def _coerce(cls, v: object) -> Decimal:
        return _to_decimal(v)

    @pydantic.model_validator(mode="after")
    def _validate(self) -> BridgeConfig:
        if self.starting_balance_dkk <= Decimal("0"):
            raise ValueError("starting_balance_dkk must be > 0")
        if self.cost_basis_dkk < Decimal("0") or self.cost_basis_dkk > self.starting_balance_dkk:
            raise ValueError(
                "cost_basis_dkk must be in [0, starting_balance_dkk]; "
                f"got {self.cost_basis_dkk} with balance {self.starting_balance_dkk}"
            )
        if self.horizon_months < 1:
            raise ValueError("horizon_months must be ≥ 1")
        if self.account_type == "ask" and self.tax_regime != "lager":
            raise ValueError("ASK accounts always use lager tax regime")
        net_rate = self.gross_annual_return_rate - self.annual_expense_ratio
        if net_rate <= Decimal("-1"):
            raise ValueError(
                "gross_annual_return_rate - annual_expense_ratio must be > -1 "
                f"(got {net_rate}); a ≤ -100 % net return cannot compound"
            )
        if self.annual_expense_ratio < Decimal("0"):
            raise ValueError("annual_expense_ratio must be ≥ 0")
        if self.annual_expense_ratio >= Decimal("1"):
            raise ValueError("annual_expense_ratio must be < 1")
        if not (Decimal("-0.5") <= self.gross_annual_return_rate <= Decimal("2")):
            raise ValueError("gross_annual_return_rate must be in [-0.5, 2.0]")
        if self.aktieindkomst_threshold_dkk <= Decimal("0"):
            raise ValueError("aktieindkomst_threshold_dkk must be > 0")
        if self.annual_dividend_yield < Decimal("0"):
            raise ValueError("annual_dividend_yield must be ≥ 0")
        if self.annual_dividend_yield >= Decimal("1"):
            raise ValueError("annual_dividend_yield must be < 1")
        if (
            self.tax_regime == "realisation"
            and self.annual_dividend_yield > Decimal("0")
        ):
            raise ValueError(
                "bridge simulator does not yet model dividend distributions "
                "during decumulation for tax_regime='realisation'; set "
                "annual_dividend_yield=0 (akkumulerende) or model the "
                "dividend at the household cashflow level. See issue #158."
            )
        return self


class BridgeResult(pydantic.BaseModel):
    """Output of :func:`compute_bridge_pmt`.

    Args:
        monthly_gross_withdrawal_dkk: Amount withdrawn from the depot each
            month (DKK).  For Lager accounts, the user receives this in full;
            separately, an annual Lager tax bill is due each December.
        monthly_net_to_pocket_dkk: Estimated monthly cash after all taxes.
            For Lager: equal to ``monthly_gross_withdrawal_dkk``; the annual
            Lager tax is deducted directly from the depot balance each
            December inside the simulation, so the user receives the full
            gross amount in their pocket (the annual tax bill is reported
            separately via ``annual_avg_lager_tax_dkk``).
            For Realisation: gross minus the embedded capital-gains tax on
            the gain fraction of each withdrawal.
        annual_avg_lager_tax_dkk: Average annual Lager mark-to-market tax
            during the bridge phase.  Zero for Realisation accounts.
        total_gross_withdrawn_dkk: Sum of all monthly withdrawals.
        total_tax_paid_dkk: Total tax paid (Lager annual + Realisation at
            withdrawal) over the full bridge period.
        final_balance_dkk: Remaining balance after all withdrawals.  Should
            be close to zero for a well-calibrated PMT.  A small residual
            (±0.5 % of starting balance) is normal due to rounding.
        monthly_flows: Month-by-month simulation details.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    monthly_gross_withdrawal_dkk: Decimal
    monthly_net_to_pocket_dkk: Decimal
    annual_avg_lager_tax_dkk: Decimal
    total_gross_withdrawn_dkk: Decimal
    total_tax_paid_dkk: Decimal
    final_balance_dkk: Decimal
    monthly_flows: tuple[MonthlyBridgeFlow, ...]


class MonthlyBridgeFlow(pydantic.BaseModel):
    """Per-month simulation step during the bridge phase."""

    model_config = pydantic.ConfigDict(frozen=True)

    month: int
    opening_balance_dkk: Decimal
    monthly_return_dkk: Decimal
    withdrawal_gross_dkk: Decimal
    withdrawal_tax_dkk: Decimal
    withdrawal_net_dkk: Decimal
    lager_tax_dkk: Decimal
    # Annual lager tax deducted at December (non-zero only when month % 12 == 0).
    closing_balance_dkk: Decimal
    cost_basis_dkk: Decimal


BridgeResult.model_rebuild()  # resolve forward ref


def _bridge_simulate(
    starting_balance: Decimal,
    cost_basis: Decimal,
    monthly_withdrawal: Decimal,
    horizon_months: int,
    monthly_net_rate: Decimal,
    account_type: str,
    tax_regime: str,
    threshold_dkk: Decimal,
    *,
    record_flows: bool = True,
) -> tuple[Decimal, list[MonthlyBridgeFlow]]:
    """Internal simulation: returns (final_balance, monthly_flows).

    When ``record_flows`` is ``False`` no :class:`MonthlyBridgeFlow` objects
    are constructed and an empty list is returned — this is the fast path
    used during PMT bracketing / binary search, where only the final
    balance matters.  The final simulation in :func:`compute_bridge_pmt`
    is always run with ``record_flows=True`` to populate the result.

    The monthly net rate is ``(1 + annual_net_before_tax_rate)^(1/12) - 1``
    where ``annual_net_before_tax_rate = gross_rate - expense_ratio``.

    Lager tax is computed and deducted annually (month 12, 24, 36, ...) based
    on the net gain *for that year*:
        gain = year_end_balance - year_start_balance + total_withdrawals_in_year

    Realisation tax is computed on the **year-to-date** realised gain, with
    the progressive bracket applied against the remaining low-bracket
    headroom.  Each month's withdrawal pays the *marginal* aktieindkomst
    tax for that month — early-year withdrawals get more 27 % headroom,
    later-year ones spill over into 42 %.  This matches the way SKAT
    settles aktieindkomst on the annual income statement.
    """
    balance = starting_balance
    current_cost_basis = cost_basis

    year_opening_balance = balance
    year_withdrawals = Decimal("0")
    ytd_realised_gain = Decimal("0")

    flows: list[MonthlyBridgeFlow] = []

    for month in range(1, horizon_months + 1):
        opening = balance

        # Monthly return
        monthly_return = _q(balance * monthly_net_rate)
        balance = balance + monthly_return

        # Withdrawal (with embedded realisation tax)
        if tax_regime == "realisation":
            if balance > Decimal("0") and current_cost_basis < balance:
                gain_fraction = (balance - current_cost_basis) / balance
            else:
                gain_fraction = Decimal("0")
            gain_portion = _q(monthly_withdrawal * gain_fraction)
            # Apply progressive bracket on YTD basis: how much 27% headroom
            # is still available for this tax year, then spill into 42%.
            low_room = max(threshold_dkk - ytd_realised_gain, Decimal("0"))
            low_portion = min(gain_portion, low_room)
            high_portion = max(gain_portion - low_portion, Decimal("0"))
            withdrawal_tax = _q(
                low_portion * AKTIEINDKOMST_LOW_RATE + high_portion * AKTIEINDKOMST_HIGH_RATE
            )
            ytd_realised_gain = _q(ytd_realised_gain + gain_portion)
            # Update cost basis: remove the cost-basis portion of the withdrawal
            cost_portion_of_withdrawal = _q(monthly_withdrawal * (Decimal("1") - gain_fraction))
            current_cost_basis = max(
                Decimal("0"), _q(current_cost_basis - cost_portion_of_withdrawal)
            )
            withdrawal_net = _q(monthly_withdrawal - withdrawal_tax)
        else:
            withdrawal_tax = Decimal("0")
            withdrawal_net = monthly_withdrawal

        balance = _q(balance - monthly_withdrawal)
        year_withdrawals += monthly_withdrawal

        # Lager tax: computed and deducted at year-end (December = month % 12 == 0)
        lager_tax = Decimal("0")
        if month % 12 == 0:
            if tax_regime == "lager":
                annual_gain = _q(balance - year_opening_balance + year_withdrawals)
                if annual_gain > Decimal("0"):
                    if account_type == "ask":
                        lager_tax = _q(annual_gain * ASK_RATE)
                    else:
                        lager_tax = compute_aktieindkomst_tax(
                            gain_dkk=annual_gain,
                            threshold_dkk=threshold_dkk,
                        )
                balance = _q(balance - lager_tax)
                year_opening_balance = balance
                year_withdrawals = Decimal("0")
            else:
                # End of tax year — reset progressive headroom tracker
                ytd_realised_gain = Decimal("0")

        if record_flows:
            flows.append(
                MonthlyBridgeFlow(
                    month=month,
                    opening_balance_dkk=opening,
                    monthly_return_dkk=monthly_return,
                    withdrawal_gross_dkk=monthly_withdrawal,
                    withdrawal_tax_dkk=withdrawal_tax,
                    withdrawal_net_dkk=withdrawal_net,
                    lager_tax_dkk=lager_tax,
                    closing_balance_dkk=balance,
                    cost_basis_dkk=current_cost_basis,
                )
            )

    return balance, flows


def compute_bridge_pmt(config: BridgeConfig) -> BridgeResult:  # noqa: PLR0912
    """Find the monthly gross withdrawal that depletes the portfolio in ``horizon_months``.

    Uses binary search over a full monthly simulation.  The simulation models:

    * Monthly compounding of the net-of-ÅOP return.
    * **Lager accounts**: annual mark-to-market tax deducted at December from
      the depot balance; the monthly withdrawal is gross (no embedded tax).
    * **Realisation accounts**: tax on the gain fraction of each withdrawal;
      the monthly withdrawal is gross, net-to-pocket is lower.

    The binary search runs 60 iterations with the PMT (``mid``) quantized
    to 0.01 DKK each step, so the PMT resolution is cent-level — well
    below the residual noise introduced by discrete annual tax timing
    and Decimal rounding inside ``_bridge_simulate``.  In practice the
    final balance after ``horizon_months`` months is a few DKK away
    from zero; the residual is returned for inspection.

    Comparison to Gemini's closed-form approach:

    * Gemini applied a flat 7 % net rate in the PMT formula, ignoring the
      distinction between ASK (8.3 % effective for 10 % gross) and frie midler
      Lager at the progressive bracket (5.7 %-7.3 % depending on gain size).
    * This implementation computes the net rate precisely from the config,
      applies the correct annual Lager tax *during* the drawdown period
      (not just during accumulation), and models the changing gain fraction
      for Realisation accounts.

    Args:
        config: Bridge configuration.

    Returns:
        :class:`BridgeResult` with the PMT, net-to-pocket amount, and full
        monthly simulation.

    Raises:
        LiquidDepotError: If ``gross_annual_return_rate - annual_expense_ratio``
            is ≤ -1 (would imply a total wipe-out), if the binary search
            cannot bracket a PMT that depletes the portfolio within the
            horizon, or if no positive PMT produces a non-negative running
            balance throughout the horizon.
    """
    annual_net_rate = config.gross_annual_return_rate - config.annual_expense_ratio
    if annual_net_rate <= Decimal("-1"):
        raise LiquidDepotError(
            f"annual net rate must be > -1 (got {annual_net_rate}); "
            "a -100 % or worse net return cannot compound"
        )
    # Monthly rate: (1 + annual_net_rate)^(1/12) - 1
    # Computed in float for Newton-precision, then back to Decimal.
    # Guard against float underflow collapsing values just above -1 down to
    # exactly -1.0 (which would produce monthly_net_rate == -1.0 and a
    # totally-wiped trajectory).  Decimal lacks a fractional pow, so we
    # accept a small float trip but reject the degenerate result.
    annual_net_float = float(annual_net_rate)
    if annual_net_float <= -1.0:
        raise LiquidDepotError(
            f"annual net rate {annual_net_rate} collapses to ≤ -100 % when "
            "converted to float for the fractional-exponent monthly-rate "
            "calculation; choose a less extreme return / expense ratio."
        )
    monthly_net_float = (1.0 + annual_net_float) ** (1.0 / 12.0) - 1.0
    if not math.isfinite(monthly_net_float):
        raise LiquidDepotError(
            f"monthly net rate is not finite (got {monthly_net_float!r}); "
            f"the annual net rate {annual_net_rate} overflowed during the "
            "fractional-exponent conversion to float.  Choose a smaller "
            "gross_annual_return_rate."
        )
    monthly_net_rate = Decimal(str(monthly_net_float))

    # PMT bounds: lower is 0; upper is starting_balance / horizon_months (no return)
    lo = Decimal("0")
    hi = _q(config.starting_balance_dkk / Decimal(str(config.horizon_months)))

    # If the initial hi under-withdraws (portfolio grows faster than we draw),
    # grow it until the simulated final balance is ≤ 0 or we give up.
    for _ in range(20):
        final_hi, _ = _bridge_simulate(
            config.starting_balance_dkk,
            config.cost_basis_dkk,
            hi,
            config.horizon_months,
            monthly_net_rate,
            config.account_type,
            config.tax_regime,
            config.aktieindkomst_threshold_dkk,
            record_flows=False,
        )
        if final_hi <= Decimal("0"):
            break
        hi = _q(hi * Decimal("2"))
    else:
        raise LiquidDepotError(
            "could not bracket a depleting PMT; the portfolio grows faster "
            "than any tested withdrawal rate. Check return / expense inputs."
        )

    # Binary search: find PMT such that final_balance ≈ 0.
    # 60 iterations is far more than needed in theory — `mid` is
    # quantized to 0.01 DKK on every step, so the search saturates at
    # cent-level resolution (~30 iterations over a typical bracket).
    # The extra headroom is cheap and keeps the loop simple.
    for _ in range(60):
        mid = _q((lo + hi) / Decimal("2"))
        final_balance, _ = _bridge_simulate(
            config.starting_balance_dkk,
            config.cost_basis_dkk,
            mid,
            config.horizon_months,
            monthly_net_rate,
            config.account_type,
            config.tax_regime,
            config.aktieindkomst_threshold_dkk,
            record_flows=False,
        )
        if final_balance > Decimal("0"):
            lo = mid  # underdrawing: need higher PMT
        else:
            hi = mid  # overdrawing: need lower PMT

    monthly_pmt = _q((lo + hi) / Decimal("2"))
    final_balance, flows = _bridge_simulate(
        config.starting_balance_dkk,
        config.cost_basis_dkk,
        monthly_pmt,
        config.horizon_months,
        monthly_net_rate,
        config.account_type,
        config.tax_regime,
        config.aktieindkomst_threshold_dkk,
    )

    # Guard against pathological cases where the search collapses to a PMT
    # that depletes the depot before the horizon ends — e.g. when the
    # starting balance is too small or the return is too negative.
    for flow in flows[:-1]:
        if flow.closing_balance_dkk < Decimal("0"):
            raise LiquidDepotError(
                f"portfolio depleted to {flow.closing_balance_dkk} DKK in "
                f"month {flow.month} of {config.horizon_months}; "
                "starting balance is too small for the requested horizon."
            )

    total_gross = _q(monthly_pmt * Decimal(str(config.horizon_months)))
    total_tax = sum((f.withdrawal_tax_dkk + f.lager_tax_dkk for f in flows), Decimal("0"))
    total_tax = _q(total_tax)

    # Average the annual lager tax over the number of full December
    # checkpoints in the horizon (i.e., tax years actually settled),
    # including any zero-tax years.  Averaging over only the non-zero
    # years would bias the headline upward.  A horizon shorter than 12
    # months has no December settlement → report zero.
    tax_year_count = config.horizon_months // 12
    if config.tax_regime == "lager" and tax_year_count > 0:
        total_lager_tax = sum((f.lager_tax_dkk for f in flows), Decimal("0"))
        avg_annual_lager = _q(total_lager_tax / Decimal(str(tax_year_count)))
    else:
        avg_annual_lager = Decimal("0")

    # Net to pocket:
    #   - Lager regime: tax is deducted from the depot balance inside
    #     `_bridge_simulate` (December of each year), so the user receives
    #     the full monthly gross withdrawal in their pocket. The PMT was
    #     solved against a post-tax depot trajectory, so monthly_pmt itself
    #     is already the sustainable in-pocket amount.
    #   - Realisation regime: tax is embedded in each monthly withdrawal
    #     (gross - tax = net).  Average it back so the headline net figure
    #     is comparable to the lager case.
    if config.tax_regime == "lager":
        monthly_net = monthly_pmt
    else:
        avg_withdrawal_tax = _q(
            sum((f.withdrawal_tax_dkk for f in flows), Decimal("0"))
            / Decimal(str(config.horizon_months))
        )
        monthly_net = _q(monthly_pmt - avg_withdrawal_tax)

    return BridgeResult(
        monthly_gross_withdrawal_dkk=monthly_pmt,
        monthly_net_to_pocket_dkk=monthly_net,
        annual_avg_lager_tax_dkk=_q(avg_annual_lager),
        total_gross_withdrawn_dkk=total_gross,
        total_tax_paid_dkk=total_tax,
        final_balance_dkk=_q(final_balance),
        monthly_flows=tuple(flows),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Fund/strategy comparison
# ──────────────────────────────────────────────────────────────────────────────


class FundProfile(pydantic.BaseModel):
    """Fund or investment instrument profile for strategy comparison.

    Args:
        label: Human-readable identifier (e.g. ``"iShares MSCI World IT ETF"``).
        isin: ISIN code (e.g. ``"IE00BJ5JNY98"``).
        account_type: ``"ask"`` or ``"frie_midler"``.
        tax_regime: ``"lager"`` or ``"realisation"``.
        gross_annual_return_rate: Expected annual return before costs.
        annual_expense_ratio: ÅOP in decimal form.
        annual_dividend_yield: Dividend yield for *udloddende* (realisation)
            funds.  Zero for akkumulerende instruments.
        tax_source: Where Lager tax is paid from.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    label: str
    isin: str
    account_type: Literal["ask", "frie_midler"]
    tax_regime: Literal["lager", "realisation"]
    gross_annual_return_rate: Decimal
    annual_expense_ratio: Decimal
    annual_dividend_yield: Decimal = Decimal("0")
    tax_source: Literal["external", "depot"] = "external"

    @pydantic.field_validator(
        "gross_annual_return_rate",
        "annual_expense_ratio",
        "annual_dividend_yield",
        mode="before",
    )
    @classmethod
    def _coerce(cls, v: object) -> Decimal:
        return _to_decimal(v)


class StrategyComparisonRow(pydantic.BaseModel):
    """Result row for one strategy in a multi-strategy comparison."""

    model_config = pydantic.ConfigDict(frozen=True)

    label: str
    isin: str
    account_type: str
    tax_regime: str
    annual_expense_ratio: Decimal
    terminal_balance_dkk: Decimal
    opening_balance_dkk: Decimal
    # Opening balance the projection started from.  Surfaced so callers can
    # reconstruct "total invested = opening + contributions" without having
    # to thread the comparison input through separately.
    total_contributions_dkk: Decimal
    # Sum of contributions actually deposited across the horizon (after ASK
    # capping for ASK accounts).  Excludes the opening balance.
    total_tax_due_dkk: Decimal
    terminal_gain_fraction: Decimal
    effective_net_annual_rate: Decimal | None
    # CAGR of the depot, ``(terminal / opening) ** (1 / years) - 1``.
    # Reported only for the **zero-contribution** case where the depot
    # compounds a single lump sum and a CAGR is meaningful.  When
    # ``total_contributions_dkk > 0`` this field is ``None`` because a
    # cashflow-aware return measure (MWRR/IRR) would be needed and is not
    # computed here.


def compare_liquid_strategies(
    fund_profiles: Sequence[FundProfile],
    *,
    opening_balance_dkk: Decimal,
    ask_lifetime_deposits_dkk: Decimal,
    monthly_contribution_dkk: Decimal,
    base_year: int,
    horizon_years: int,
    aktieindkomst_threshold_dkk: Decimal | None = None,
) -> list[StrategyComparisonRow]:
    """Compare multiple fund profiles on the same opening balance and contribution.

    Each profile is run through :func:`project_liquid` with identical starting
    conditions; the results are sorted by terminal balance (best first).

    For ASK profiles, the deposit cap limits how much can go in; excess
    contributions are dropped (the cap is a hard constraint, not overrideable).
    For a fair comparison with frie midler profiles, consider running both with
    an ASK-sized opening balance.

    Args:
        fund_profiles: List of fund/instrument profiles to compare.
        opening_balance_dkk: Starting portfolio value (DKK).
        ask_lifetime_deposits_dkk: Cumulative ASK deposits to date (DKK).
            Ignored for frie midler profiles.
        monthly_contribution_dkk: Monthly savings amount (DKK).
        base_year: Year before the first projected year.
        horizon_years: Number of years to project.
        aktieindkomst_threshold_dkk: Override the progressive bracket threshold.
            Defaults to :func:`threshold_for_year(base_year + 1)`.

    Returns:
        List of :class:`StrategyComparisonRow`, sorted by terminal balance
        (descending — best outcome first).
    """
    if aktieindkomst_threshold_dkk is None:
        aktieindkomst_threshold_dkk = threshold_for_year(base_year + 1)

    rows: list[StrategyComparisonRow] = []
    annual_contribution = _q(monthly_contribution_dkk * Decimal("12"))

    for fp in fund_profiles:
        cfg = LiquidDepotConfig(
            account_id=fp.isin,
            account_type=fp.account_type,
            tax_regime=fp.tax_regime,
            opening_balance_dkk=opening_balance_dkk,
            ask_lifetime_deposits_dkk=ask_lifetime_deposits_dkk,
            annual_contribution_dkk=annual_contribution,
            gross_annual_return_rate=fp.gross_annual_return_rate,
            annual_expense_ratio=fp.annual_expense_ratio,
            annual_dividend_yield=fp.annual_dividend_yield,
            tax_source=fp.tax_source,
            aktieindkomst_threshold_dkk=aktieindkomst_threshold_dkk,
        )
        proj = project_liquid(cfg, base_year=base_year, horizon_years=horizon_years)

        terminal = proj.terminal_balance_dkk()
        total_contributions = proj.total_contributions_dkk()

        # Effective net annual rate is only meaningful when no contributions
        # are added (pure lump-sum compounding).  With contributions the
        # CAGR would mix capital and return and mislead callers; expose
        # ``None`` and document that MWRR/IRR is the right metric there.
        effective_rate: Decimal | None
        if total_contributions > Decimal("0"):
            effective_rate = None
        elif terminal > Decimal("0") and opening_balance_dkk > Decimal("0"):
            ratio_float = float(terminal / opening_balance_dkk)
            # Quantize to 0.0001 (1 basis point) — the field is a *rate*,
            # not a money amount.  The money-style 0.01 quantizer would
            # round 0.078 → 0.08 (~10 % error in the reported rate).
            effective_rate = Decimal(
                str(ratio_float ** (1.0 / horizon_years) - 1.0)
            ).quantize(Decimal("0.0001"))
        else:
            effective_rate = Decimal("0")

        rows.append(
            StrategyComparisonRow(
                label=fp.label,
                isin=fp.isin,
                account_type=fp.account_type,
                tax_regime=fp.tax_regime,
                annual_expense_ratio=fp.annual_expense_ratio,
                terminal_balance_dkk=terminal,
                opening_balance_dkk=opening_balance_dkk,
                total_contributions_dkk=total_contributions,
                total_tax_due_dkk=proj.total_tax_due_dkk(),
                terminal_gain_fraction=proj.terminal_gain_fraction,
                effective_net_annual_rate=effective_rate,
            )
        )

    rows.sort(key=lambda r: r.terminal_balance_dkk, reverse=True)
    return rows
