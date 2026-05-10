"""Demo defaults for the projection dashboard (#33).

The dashboard must render out-of-the-box without requiring a separate
configuration file. This module provides synthetic-but-plausible
factories for the four sim inputs (cashflow, tax, return-model, MC
config) so the page is interactive on a fresh checkout.

Real-deployment users override these via the sidebar widgets — and a
later issue will swap the synthetic return-history for a fitted one
sourced from market data (tracked under the existing
``BootstrapReturnModel`` improvements).

All values are deliberately conservative round numbers, not
representations of any real household balance sheet.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final, Literal

import numpy as np

from penge.sim.cashflow import (
    CashflowConfig,
    ContributionRule,
    PensionAccrualRule,
    SalaryRule,
)
from penge.sim.goal import GoalConfig
from penge.sim.montecarlo import MonteCarloConfig
from penge.sim.returns import BootstrapReturnModel
from penge.sim.tax import TaxConfig

DEFAULT_BASE_YEAR: Final[int] = 2024
DEFAULT_HORIZON_YEARS: Final[int] = 30
DEFAULT_INITIAL_PORTFOLIO_EUR: Final[Decimal] = Decimal("250000")
DEFAULT_TARGET_ANNUAL_EUR: Final[Decimal] = Decimal("36000")
DEFAULT_SWR_RATE: Final[Decimal] = Decimal("0.0325")
DEFAULT_CAPITAL_GAINS_RATE: Final[Decimal] = Decimal("0.27")
DEFAULT_N_PATHS: Final[int] = 2_000

_EUR: Final[Literal["EUR"]] = "EUR"
_HISTORY_MONTHS: Final[int] = 240
_HISTORY_SEED: Final[int] = 42


def default_cashflow_config(
    *,
    base_year: int = DEFAULT_BASE_YEAR,
    horizon_years: int = DEFAULT_HORIZON_YEARS,
) -> CashflowConfig:
    """Return a minimal one-entity cashflow config for the demo."""
    return CashflowConfig(
        base_year=base_year,
        horizon_years=horizon_years,
        inflation_rate=Decimal("0.02"),
        eur_per_dkk=Decimal("0.134"),
        salaries=(
            SalaryRule(
                entity="demo",
                currency=_EUR,
                gross_annual=Decimal("60000"),
                real_wage_growth=Decimal("0"),
            ),
        ),
        contributions=(
            ContributionRule(
                entity="demo",
                currency=_EUR,
                annual=Decimal("12000"),
                index_to_inflation=True,
            ),
        ),
        pension_rules=(
            PensionAccrualRule(
                entity="demo",
                kind="dc_fraction",
                dc_fraction=Decimal("0.10"),
                vesting_year=base_year + horizon_years,
            ),
        ),
    )


def default_tax_config() -> TaxConfig:
    """Return a no-op (gross-mode) tax config; the runner still applies
    ``capital_gains_effective_rate`` from the MC config to portfolio gains.
    """
    return TaxConfig(enabled=False)


def default_goal(
    *,
    target_annual_eur: Decimal = DEFAULT_TARGET_ANNUAL_EUR,
    swr_rate: Decimal = DEFAULT_SWR_RATE,
) -> GoalConfig:
    return GoalConfig(
        target_annual_eur=target_annual_eur,
        swr_rate=swr_rate,
        require_all_vested=False,
    )


def default_return_model(
    *,
    seed: int = 0,
    n_months: int = _HISTORY_MONTHS,
) -> BootstrapReturnModel:
    """Synthetic two-asset monthly history; deterministic by ``seed``.

    Equity-like series: ~7 %/yr drift, ~15 %/yr vol.
    Bond-like series:   ~2 %/yr drift, ~5 %/yr vol.
    Inflation: a flat 2 %/yr both DE and DK.
    """
    rng = np.random.default_rng(_HISTORY_SEED)
    equity = rng.normal(loc=0.07 / 12, scale=0.15 / np.sqrt(12), size=n_months)
    bonds = rng.normal(loc=0.02 / 12, scale=0.05 / np.sqrt(12), size=n_months)
    return BootstrapReturnModel(
        asset_returns={
            "equity": [Decimal(str(round(float(x), 8))) for x in equity],
            "bonds": [Decimal(str(round(float(x), 8))) for x in bonds],
        },
        inflation={
            "de": [Decimal("0.001651")] * n_months,
            "dk": [Decimal("0.001651")] * n_months,
        },
        block_months=12,
        seed=seed,
    )


def default_mc_config(
    *,
    n_paths: int = DEFAULT_N_PATHS,
    initial_portfolio_eur: Decimal = DEFAULT_INITIAL_PORTFOLIO_EUR,
    capital_gains_effective_rate: Decimal = DEFAULT_CAPITAL_GAINS_RATE,
    equity_weight: Decimal = Decimal("0.7"),
) -> MonteCarloConfig:
    bond_weight = Decimal("1") - equity_weight
    return MonteCarloConfig(
        n_paths=n_paths,
        asset_weights={"equity": equity_weight, "bonds": bond_weight},
        initial_portfolio_eur=initial_portfolio_eur,
        capital_gains_effective_rate=capital_gains_effective_rate,
    )
