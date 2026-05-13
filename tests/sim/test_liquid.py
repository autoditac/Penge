"""Tests for penge.sim.liquid — tax-aware liquid depot projection engine.

All fixtures use synthetic data only.  Arithmetic is verified by hand or with
simple spreadsheet-style calculations in comments.

Coverage:
* Unit — progressive Aktieindkomst tax helper
* ASK projection (flat 17 % lager, cap enforcement)
* Frie midler Lager (progressive brackets, single bracket, crossover)
* Frie midler Realisation (deferred capital gain, dividend tracking)
* External vs depot tax source
* Bridge / decumulation PMT (Lager and Realisation)
* Strategy comparison sort order
* Config validation edge cases
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

import pydantic
import pytest

from penge.sim.liquid import (
    BridgeConfig,
    FundProfile,
    LiquidDepotConfig,
    LiquidDepotError,
    StrategyComparisonRow,
    ask_cap_for_year,
    compare_liquid_strategies,
    compute_aktieindkomst_tax,
    compute_bridge_pmt,
    project_liquid,
    threshold_for_year,
)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _ask_config(
    *,
    opening: str = "62000",
    lifetime_deposits: str = "62000",
    annual_contribution: str = "0",
    gross_rate: str = "0.10",
    aop: str = "0.0012",
) -> LiquidDepotConfig:
    return LiquidDepotConfig(
        account_id="test-ask",
        account_type="ask",
        tax_regime="lager",
        opening_balance_dkk=Decimal(opening),
        ask_lifetime_deposits_dkk=Decimal(lifetime_deposits),
        annual_contribution_dkk=Decimal(annual_contribution),
        gross_annual_return_rate=Decimal(gross_rate),
        annual_expense_ratio=Decimal(aop),
        aktieindkomst_threshold_dkk=Decimal("61900"),
    )


def _frie_lager_config(
    *,
    opening: str = "400000",
    annual_contribution: str = "0",
    gross_rate: str = "0.10",
    aop: str = "0.0012",
    tax_source: Literal["external", "depot"] = "external",
) -> LiquidDepotConfig:
    return LiquidDepotConfig(
        account_id="test-frie-lager",
        account_type="frie_midler",
        tax_regime="lager",
        opening_balance_dkk=Decimal(opening),
        annual_contribution_dkk=Decimal(annual_contribution),
        gross_annual_return_rate=Decimal(gross_rate),
        annual_expense_ratio=Decimal(aop),
        tax_source=tax_source,
        aktieindkomst_threshold_dkk=Decimal("61900"),
    )


def _frie_realisation_config(
    *,
    opening: str = "200000",
    annual_contribution: str = "0",
    gross_rate: str = "0.10",
    aop: str = "0.0049",
    dividend_yield: str = "0.005",
    tax_source: Literal["external", "depot"] = "external",
) -> LiquidDepotConfig:
    return LiquidDepotConfig(
        account_id="test-frie-real",
        account_type="frie_midler",
        tax_regime="realisation",
        opening_balance_dkk=Decimal(opening),
        annual_contribution_dkk=Decimal(annual_contribution),
        gross_annual_return_rate=Decimal(gross_rate),
        annual_expense_ratio=Decimal(aop),
        annual_dividend_yield=Decimal(dividend_yield),
        tax_source=tax_source,
        aktieindkomst_threshold_dkk=Decimal("61900"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Unit tests: progressive tax helper
# ─────────────────────────────────────────────────────────────────────────────


class TestComputeAktieindkomstTax:
    def test_zero_gain_returns_zero(self) -> None:
        assert compute_aktieindkomst_tax(
            gain_dkk=Decimal("0"), threshold_dkk=Decimal("61900")
        ) == Decimal("0")

    def test_negative_gain_returns_zero(self) -> None:
        assert compute_aktieindkomst_tax(
            gain_dkk=Decimal("-5000"), threshold_dkk=Decimal("61900")
        ) == Decimal("0")

    def test_gain_entirely_in_low_bracket(self) -> None:
        # 30 000 * 0.27 = 8 100.00
        result = compute_aktieindkomst_tax(
            gain_dkk=Decimal("30000"), threshold_dkk=Decimal("61900")
        )
        assert result == Decimal("8100.00")

    def test_gain_exactly_at_threshold(self) -> None:
        # 61 900 * 0.27 = 16 713.00
        result = compute_aktieindkomst_tax(
            gain_dkk=Decimal("61900"), threshold_dkk=Decimal("61900")
        )
        assert result == Decimal("16713.00")

    def test_gain_spans_both_brackets(self) -> None:
        # low: 61 900 * 0.27 = 16 713.00
        # high: 38 100 * 0.42 = 16 002.00
        # total: 32 715.00
        result = compute_aktieindkomst_tax(
            gain_dkk=Decimal("100000"), threshold_dkk=Decimal("61900")
        )
        assert result == Decimal("32715.00")

    def test_gain_entirely_in_high_bracket(self) -> None:
        # low: 61 900 * 0.27 = 16 713.00
        # high: 238 100 * 0.42 = 100 002.00
        # total: 116 715.00
        result = compute_aktieindkomst_tax(
            gain_dkk=Decimal("300000"), threshold_dkk=Decimal("61900")
        )
        assert result == Decimal("116715.00")

    def test_effective_rate_large_gain_approaches_42_percent(self) -> None:
        result = compute_aktieindkomst_tax(
            gain_dkk=Decimal("10000000"), threshold_dkk=Decimal("61900")
        )
        effective = result / Decimal("10000000")
        assert effective > Decimal("0.419")  # approaches but never reaches 42%

    def test_custom_rates(self) -> None:
        # Verify the formula works with overridden rates
        result = compute_aktieindkomst_tax(
            gain_dkk=Decimal("100000"),
            threshold_dkk=Decimal("50000"),
            low_rate=Decimal("0.20"),
            high_rate=Decimal("0.40"),
        )
        # 50 000 * 0.20 + 50 000 * 0.40 = 10 000 + 20 000 = 30 000
        assert result == Decimal("30000.00")


# ─────────────────────────────────────────────────────────────────────────────
# Unit tests: threshold and cap lookups
# ─────────────────────────────────────────────────────────────────────────────


class TestThresholdForYear:
    def test_known_year_returns_exact_value(self) -> None:
        assert threshold_for_year(2024) == Decimal("61900")

    def test_future_year_falls_back_to_last_known(self) -> None:
        # Should not raise; falls back to last entry in AKTIEINDKOMST_THRESHOLDS
        result = threshold_for_year(2099)
        assert result > Decimal("0")

    def test_known_2025_estimate(self) -> None:
        result = threshold_for_year(2025)
        assert result > Decimal("61900")  # indexed upward

    def test_past_year_before_table_raises(self) -> None:
        with pytest.raises(LiquidDepotError, match="no aktieindkomst threshold"):
            threshold_for_year(2020)


class TestAskCapForYear:
    def test_known_year(self) -> None:
        assert ask_cap_for_year(2025) == Decimal("142500")

    def test_2026_estimated(self) -> None:
        cap_2026 = ask_cap_for_year(2026)
        assert cap_2026 > Decimal("142500")  # estimated increase

    def test_far_future_fallback(self) -> None:
        # Should not raise; falls back to last known cap
        cap = ask_cap_for_year(2099)
        assert cap > Decimal("0")


# ─────────────────────────────────────────────────────────────────────────────
# ASK projection tests
# ─────────────────────────────────────────────────────────────────────────────


class TestProjectLiquidAsk:
    def test_single_year_no_contribution(self) -> None:
        """Verify ASK 17% flat rate calculation for one year."""
        # opening = 62 000, net_rate = 0.10 - 0.0012 = 0.0988
        # gross_return = 62 000 * 0.0988 = 6 125.60
        # tax = 6 125.60 * 0.17 = 1 041.35 (rounded)
        # external tax source → balance = 62 000 + 6 125.60 = 68 125.60
        cfg = _ask_config(opening="62000", lifetime_deposits="62000")
        proj = project_liquid(cfg, base_year=2024, horizon_years=1)

        assert len(proj.flows) == 1
        flow = proj.flows[0]
        assert flow.year == 2025
        assert flow.opening_balance_dkk == Decimal("62000")

        expected_return = Decimal("62000") * (Decimal("0.10") - Decimal("0.0012"))
        assert abs(flow.gross_return_dkk - expected_return) < Decimal("0.02")

        expected_tax = (flow.gross_return_dkk * Decimal("0.17")).quantize(Decimal("0.01"))
        assert abs(flow.tax_due_dkk - expected_tax) < Decimal("0.02")
        # External source → no deduction from depot
        assert flow.tax_deducted_from_depot_dkk == Decimal("0")

    def test_depot_tax_source_reduces_balance(self) -> None:
        cfg = LiquidDepotConfig(
            account_id="ask-depot",
            account_type="ask",
            tax_regime="lager",
            opening_balance_dkk=Decimal("62000"),
            ask_lifetime_deposits_dkk=Decimal("62000"),
            annual_contribution_dkk=Decimal("0"),
            gross_annual_return_rate=Decimal("0.10"),
            annual_expense_ratio=Decimal("0.0012"),
            tax_source="depot",
            aktieindkomst_threshold_dkk=Decimal("61900"),
        )
        proj = project_liquid(cfg, base_year=2024, horizon_years=1)
        flow = proj.flows[0]
        # Depot tax deducted
        assert flow.tax_deducted_from_depot_dkk == flow.tax_due_dkk
        # Balance is lower than external-source case
        external_proj = project_liquid(_ask_config(), base_year=2024, horizon_years=1)
        assert flow.closing_balance_dkk < external_proj.flows[0].closing_balance_dkk

    def test_ask_cap_limits_contribution(self) -> None:
        """Contributions to ASK are capped at the remaining lifetime cap room."""
        # lifetime deposits = 141 000, 2025 cap = 142 500, room = 1 500 DKK
        cfg = _ask_config(
            lifetime_deposits="141000",
            annual_contribution="20000",  # would exceed cap
        )
        proj = project_liquid(cfg, base_year=2024, horizon_years=1)
        flow = proj.flows[0]
        assert flow.annual_contribution_dkk == Decimal("1500")
        assert flow.cumulative_ask_deposits_dkk == Decimal("142500")

    def test_ask_cap_exhausted_no_contribution(self) -> None:
        """No contributions allowed when cap is fully used."""
        cfg = _ask_config(
            lifetime_deposits="142500",  # 2025 cap
            annual_contribution="10000",
        )
        proj = project_liquid(cfg, base_year=2024, horizon_years=1)
        assert proj.flows[0].annual_contribution_dkk == Decimal("0")

    def test_ask_multi_year_compounding(self) -> None:
        """Ten-year ASK projection with no contributions — verify monotone growth."""
        cfg = _ask_config(opening="100000", lifetime_deposits="100000")
        proj = project_liquid(cfg, base_year=2024, horizon_years=10)

        assert len(proj.flows) == 10
        for i in range(1, len(proj.flows)):
            assert proj.flows[i].closing_balance_dkk > proj.flows[i - 1].closing_balance_dkk

    def test_ask_terminal_gain_fraction_is_zero(self) -> None:
        """ASK uses lager; all gains taxed annually; gain fraction at end = 0."""
        cfg = _ask_config(opening="100000", lifetime_deposits="100000")
        proj = project_liquid(cfg, base_year=2024, horizon_years=5)
        assert proj.terminal_gain_fraction == Decimal("0")

    def test_ask_invalid_realisation_regime(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            LiquidDepotConfig(
                account_id="bad",
                account_type="ask",
                tax_regime="realisation",
                opening_balance_dkk=Decimal("1000"),
                annual_contribution_dkk=Decimal("0"),
                gross_annual_return_rate=Decimal("0.10"),
                annual_expense_ratio=Decimal("0.001"),
                aktieindkomst_threshold_dkk=Decimal("61900"),
            )


# ─────────────────────────────────────────────────────────────────────────────
# Frie midler — Lager (progressive)
# ─────────────────────────────────────────────────────────────────────────────


class TestProjectLiquidFrieLager:
    def test_small_balance_stays_in_low_bracket(self) -> None:
        """A 200 000 DKK depot earning ~9.88% net = ~19 760 DKK gain, all in 27% bracket."""
        # 200 000 * 0.0988 = 19 760, threshold = 61 900 → all at 27%
        # tax = 19 760 * 0.27 = 5 335.20
        cfg = _frie_lager_config(opening="200000")
        proj = project_liquid(cfg, base_year=2024, horizon_years=1)
        flow = proj.flows[0]
        expected_tax = compute_aktieindkomst_tax(
            gain_dkk=flow.gross_return_dkk, threshold_dkk=Decimal("61900")
        )
        assert flow.tax_due_dkk == expected_tax
        # Effective rate should be 27%
        effective_rate = flow.tax_due_dkk / flow.gross_return_dkk
        assert abs(effective_rate - Decimal("0.27")) < Decimal("0.001")

    def test_large_balance_crosses_bracket(self) -> None:
        """A 700 000 DKK depot gain = ~69 160 DKK, crosses the 61 900 threshold."""
        cfg = _frie_lager_config(opening="700000")
        proj = project_liquid(cfg, base_year=2024, horizon_years=1)
        flow = proj.flows[0]
        # Gain ~69 160 > 61 900 → effective rate between 27% and 42%
        effective_rate = flow.tax_due_dkk / flow.gross_return_dkk
        assert effective_rate > Decimal("0.27")
        assert effective_rate < Decimal("0.42")

    def test_external_tax_source_does_not_reduce_balance(self) -> None:
        cfg = _frie_lager_config(opening="300000", tax_source="external")
        proj = project_liquid(cfg, base_year=2024, horizon_years=1)
        flow = proj.flows[0]
        assert flow.tax_deducted_from_depot_dkk == Decimal("0")
        # Balance = opening + full gross return (no tax deduction)
        expected = flow.opening_balance_dkk + flow.gross_return_dkk
        assert abs(flow.closing_balance_dkk - expected) < Decimal("0.02")

    def test_depot_tax_source_reduces_balance_by_tax(self) -> None:
        cfg = _frie_lager_config(opening="300000", tax_source="depot")
        proj = project_liquid(cfg, base_year=2024, horizon_years=1)
        flow = proj.flows[0]
        assert flow.tax_deducted_from_depot_dkk == flow.tax_due_dkk
        expected = flow.opening_balance_dkk + flow.gross_return_dkk - flow.tax_due_dkk
        assert abs(flow.closing_balance_dkk - expected) < Decimal("0.02")

    def test_frie_lager_terminal_gain_fraction_zero(self) -> None:
        """Lager: all gains taxed annually → no deferred gain at end."""
        cfg = _frie_lager_config(opening="500000")
        proj = project_liquid(cfg, base_year=2024, horizon_years=10)
        assert proj.terminal_gain_fraction == Decimal("0")

    def test_frie_lager_grows_more_slowly_than_ask(self) -> None:
        """For same gross return, ASK (17%) beats frie midler Lager (27-42%)."""
        ask_cfg = _ask_config(
            opening="100000",
            lifetime_deposits="80000",
            gross_rate="0.10",
            aop="0.0012",
        )
        frie_cfg = _frie_lager_config(
            opening="100000",
            gross_rate="0.10",
            aop="0.0012",
            tax_source="depot",
        )
        ask_proj = project_liquid(ask_cfg, base_year=2024, horizon_years=10)
        frie_proj = project_liquid(frie_cfg, base_year=2024, horizon_years=10)
        # ASK pays less tax (17% vs 27%+), so terminal balance is higher
        assert ask_proj.terminal_balance_dkk() > frie_proj.terminal_balance_dkk()


# ─────────────────────────────────────────────────────────────────────────────
# Frie midler — Realisationsbeskatning
# ─────────────────────────────────────────────────────────────────────────────


class TestProjectLiquidFrieRealisation:
    def test_only_dividend_taxed_annually(self) -> None:
        """For realisation regime: annual tax is based on dividend yield only."""
        cfg = _frie_realisation_config(opening="200000", dividend_yield="0.005")
        proj = project_liquid(cfg, base_year=2024, horizon_years=1)
        flow = proj.flows[0]

        # Dividend = 200 000 * 0.005 = 1 000 DKK
        expected_dividend_gross = Decimal("200000") * Decimal("0.005")
        assert abs(flow.taxable_gain_dkk - expected_dividend_gross) < Decimal("0.02")

        # Tax = 1 000 * 0.27 (all below threshold)
        expected_tax = expected_dividend_gross * Decimal("0.27")
        assert abs(flow.tax_due_dkk - expected_tax) < Decimal("0.02")

        # Gross return = 200 000 * (0.10 - 0.0049) = 200 000 * 0.0951 = 19 020
        # Capital appreciation = gross_return - dividend_gross = 19 020 - 1 000 = 18 020
        # Net dividend = 1 000 - 270 = 730
        # balance = 200 000 + 18 020 + 730 = 218 750
        expected_capital_appreciation = Decimal("200000") * (
            Decimal("0.10") - Decimal("0.0049") - Decimal("0.005")
        )
        expected_balance = (
            Decimal("200000")
            + expected_capital_appreciation
            + (expected_dividend_gross - expected_tax)
        )
        assert abs(flow.closing_balance_dkk - expected_balance) < Decimal("1.00")

    def test_cost_basis_tracked_correctly(self) -> None:
        """Cost basis increases by contributions and net dividends."""
        cfg = _frie_realisation_config(
            opening="200000",
            annual_contribution="12000",
            dividend_yield="0.005",
        )
        proj = project_liquid(cfg, base_year=2024, horizon_years=1)
        flow = proj.flows[0]

        # cost_basis = opening + contribution + net_dividend
        expected_basis = Decimal("200000") + Decimal("12000") + flow.dividend_received_net_dkk
        assert abs(flow.cost_basis_dkk - expected_basis) < Decimal("0.02")

    def test_terminal_gain_fraction_non_zero(self) -> None:
        """Realisation: capital gains deferred → gain fraction > 0 at terminal."""
        cfg = _frie_realisation_config(opening="200000", dividend_yield="0.005")
        proj = project_liquid(cfg, base_year=2024, horizon_years=10)
        assert proj.terminal_gain_fraction > Decimal("0")

    def test_realisation_better_than_lager_long_horizon(self) -> None:
        """Realisation defers capital gain tax — better than Lager over 20 years."""
        # Same gross return, same ÅOP, same opening balance
        real_cfg = _frie_realisation_config(
            opening="300000",
            gross_rate="0.10",
            aop="0.0049",
            dividend_yield="0.005",
            tax_source="depot",
        )
        lager_cfg = _frie_lager_config(
            opening="300000", gross_rate="0.10", aop="0.0049", tax_source="depot"
        )
        real_proj = project_liquid(real_cfg, base_year=2024, horizon_years=20)
        lager_proj = project_liquid(lager_cfg, base_year=2024, horizon_years=20)
        # Realisation defers tax → higher balance (note: at liquidation the deferred
        # tax is still owed, but during accumulation the pretax balance is higher)
        assert real_proj.terminal_balance_dkk() > lager_proj.terminal_balance_dkk()

    def test_zero_dividend_yield_accumulation_fund(self) -> None:
        """Akkumulerende fund: no annual tax; balance grows unimpeded."""
        cfg = LiquidDepotConfig(
            account_id="test-akkum",
            account_type="frie_midler",
            tax_regime="realisation",
            opening_balance_dkk=Decimal("200000"),
            annual_contribution_dkk=Decimal("0"),
            gross_annual_return_rate=Decimal("0.10"),
            annual_expense_ratio=Decimal("0.0049"),
            annual_dividend_yield=Decimal("0"),
            tax_source="external",
            aktieindkomst_threshold_dkk=Decimal("61900"),
        )
        proj = project_liquid(cfg, base_year=2024, horizon_years=5)
        for flow in proj.flows:
            assert flow.tax_due_dkk == Decimal("0")
            assert flow.taxable_gain_dkk == Decimal("0")


# ─────────────────────────────────────────────────────────────────────────────
# Config validation
# ─────────────────────────────────────────────────────────────────────────────


class TestLiquidDepotConfigValidation:
    def test_negative_opening_balance_rejected(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            LiquidDepotConfig(
                account_id="x",
                account_type="frie_midler",
                tax_regime="lager",
                opening_balance_dkk=Decimal("-1"),
                annual_contribution_dkk=Decimal("0"),
                gross_annual_return_rate=Decimal("0.10"),
                annual_expense_ratio=Decimal("0.001"),
                aktieindkomst_threshold_dkk=Decimal("61900"),
            )

    def test_ask_with_realisation_rejected(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            LiquidDepotConfig(
                account_id="x",
                account_type="ask",
                tax_regime="realisation",
                opening_balance_dkk=Decimal("1000"),
                annual_contribution_dkk=Decimal("0"),
                gross_annual_return_rate=Decimal("0.10"),
                annual_expense_ratio=Decimal("0.001"),
                aktieindkomst_threshold_dkk=Decimal("61900"),
            )

    def test_ask_with_nonzero_dividend_yield_rejected(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            LiquidDepotConfig(
                account_id="x",
                account_type="ask",
                tax_regime="lager",
                opening_balance_dkk=Decimal("1000"),
                annual_contribution_dkk=Decimal("0"),
                gross_annual_return_rate=Decimal("0.10"),
                annual_expense_ratio=Decimal("0.001"),
                annual_dividend_yield=Decimal("0.01"),
                aktieindkomst_threshold_dkk=Decimal("61900"),
            )

    def test_horizon_zero_rejected(self) -> None:
        cfg = _ask_config()
        with pytest.raises(LiquidDepotError):
            project_liquid(cfg, base_year=2024, horizon_years=0)

    def test_string_decimal_coercion(self) -> None:
        """Pydantic should coerce string values to Decimal."""
        cfg = LiquidDepotConfig(
            account_id="x",
            account_type="ask",
            tax_regime="lager",
            opening_balance_dkk="62000",  # type: ignore[arg-type]  # intentional: verifying Pydantic str→Decimal coercion
            annual_contribution_dkk="1000",  # type: ignore[arg-type]  # intentional: verifying Pydantic str→Decimal coercion
            gross_annual_return_rate="0.10",  # type: ignore[arg-type]  # intentional: verifying Pydantic str→Decimal coercion
            annual_expense_ratio="0.001",  # type: ignore[arg-type]  # intentional: verifying Pydantic str→Decimal coercion
            aktieindkomst_threshold_dkk="61900",  # type: ignore[arg-type]  # intentional: verifying Pydantic str→Decimal coercion
        )
        assert cfg.opening_balance_dkk == Decimal("62000")

    def test_nan_rejected(self) -> None:
        with pytest.raises(pydantic.ValidationError, match="finite"):
            LiquidDepotConfig(
                account_id="x",
                account_type="frie_midler",
                tax_regime="lager",
                opening_balance_dkk="NaN",  # type: ignore[arg-type]  # intentional: verifying NaN rejection
                annual_contribution_dkk=Decimal("0"),
                gross_annual_return_rate=Decimal("0.10"),
                annual_expense_ratio=Decimal("0.001"),
                aktieindkomst_threshold_dkk=Decimal("61900"),
            )

    def test_infinity_rejected(self) -> None:
        with pytest.raises(pydantic.ValidationError, match="finite"):
            LiquidDepotConfig(
                account_id="x",
                account_type="frie_midler",
                tax_regime="lager",
                opening_balance_dkk="Infinity",  # type: ignore[arg-type]  # intentional: verifying Infinity rejection
                annual_contribution_dkk=Decimal("0"),
                gross_annual_return_rate=Decimal("0.10"),
                annual_expense_ratio=Decimal("0.001"),
                aktieindkomst_threshold_dkk=Decimal("61900"),
            )


# ─────────────────────────────────────────────────────────────────────────────
# Bridge / decumulation PMT
# ─────────────────────────────────────────────────────────────────────────────


class TestComputeBridgePmt:
    """All tests verify PMT is found and that the final balance is near zero."""

    _TOLERANCE_PCT = Decimal("0.005")  # 0.5% of starting balance

    def _tolerance(self, starting: Decimal) -> Decimal:
        return starting * self._TOLERANCE_PCT

    def test_ask_lager_120_months(self) -> None:
        """ASK 17% Lager: binary-search PMT depletes in 120 months."""
        cfg = BridgeConfig(
            starting_balance_dkk=Decimal("3250000"),
            cost_basis_dkk=Decimal("3250000"),  # lager: all gains taxed already
            horizon_months=120,
            gross_annual_return_rate=Decimal("0.10"),
            annual_expense_ratio=Decimal("0.0012"),
            account_type="ask",
            tax_regime="lager",
            aktieindkomst_threshold_dkk=Decimal("61900"),
        )
        result = compute_bridge_pmt(cfg)
        assert abs(result.final_balance_dkk) < self._tolerance(cfg.starting_balance_dkk)
        assert result.monthly_gross_withdrawal_dkk > Decimal("0")
        # Sanity: monthly gross should be roughly in range 30 000 - 50 000 DKK
        assert result.monthly_gross_withdrawal_dkk > Decimal("30000")
        assert result.monthly_gross_withdrawal_dkk < Decimal("60000")

    def test_frie_lager_120_months(self) -> None:
        """Frie midler Lager: annual mark-to-market tax deducted from depot during bridge."""
        cfg = BridgeConfig(
            starting_balance_dkk=Decimal("3000000"),
            cost_basis_dkk=Decimal("3000000"),
            horizon_months=120,
            gross_annual_return_rate=Decimal("0.10"),
            annual_expense_ratio=Decimal("0.0012"),
            account_type="frie_midler",
            tax_regime="lager",
            aktieindkomst_threshold_dkk=Decimal("61900"),
        )
        result = compute_bridge_pmt(cfg)
        assert abs(result.final_balance_dkk) < self._tolerance(cfg.starting_balance_dkk)
        assert result.monthly_gross_withdrawal_dkk > Decimal("0")
        # Annual Lager tax is non-zero
        assert result.annual_avg_lager_tax_dkk > Decimal("0")

    def test_frie_realisation_120_months(self) -> None:
        """Realisation: embedded tax on gain fraction of each withdrawal."""
        # With gain fraction ~40%, each withdrawal has ~40% taxed
        cfg = BridgeConfig(
            starting_balance_dkk=Decimal("3000000"),
            cost_basis_dkk=Decimal("1800000"),  # gain fraction = 40%
            horizon_months=120,
            gross_annual_return_rate=Decimal("0.10"),
            annual_expense_ratio=Decimal("0.0049"),
            account_type="frie_midler",
            tax_regime="realisation",
            aktieindkomst_threshold_dkk=Decimal("61900"),
        )
        result = compute_bridge_pmt(cfg)
        assert abs(result.final_balance_dkk) < self._tolerance(cfg.starting_balance_dkk)
        # No annual Lager tax for realisation accounts
        assert result.annual_avg_lager_tax_dkk == Decimal("0")
        # Total tax paid is positive (withdrawal tax)
        assert result.total_tax_paid_dkk > Decimal("0")

    def test_monthly_net_equals_gross_for_lager_depot_tax(self) -> None:
        """For Lager accounts, monthly net == monthly gross.

        Lager tax is deducted from the depot balance each December inside
        ``_bridge_simulate``, so the user receives the full gross monthly
        withdrawal in their pocket; the PMT is solved against the
        post-tax depot trajectory.  The annual lager tax is reported
        separately via ``annual_avg_lager_tax_dkk``.
        """
        cfg = BridgeConfig(
            starting_balance_dkk=Decimal("2000000"),
            cost_basis_dkk=Decimal("2000000"),
            horizon_months=120,
            gross_annual_return_rate=Decimal("0.10"),
            annual_expense_ratio=Decimal("0.0012"),
            account_type="frie_midler",
            tax_regime="lager",
            aktieindkomst_threshold_dkk=Decimal("61900"),
        )
        result = compute_bridge_pmt(cfg)
        assert result.monthly_net_to_pocket_dkk == result.monthly_gross_withdrawal_dkk
        assert result.annual_avg_lager_tax_dkk > Decimal("0")

    def test_total_gross_withdrawn_equals_pmt_times_months(self) -> None:
        cfg = BridgeConfig(
            starting_balance_dkk=Decimal("1000000"),
            cost_basis_dkk=Decimal("1000000"),
            horizon_months=60,
            gross_annual_return_rate=Decimal("0.08"),
            annual_expense_ratio=Decimal("0.001"),
            account_type="ask",
            tax_regime="lager",
            aktieindkomst_threshold_dkk=Decimal("61900"),
        )
        result = compute_bridge_pmt(cfg)
        expected_total = result.monthly_gross_withdrawal_dkk * Decimal("60")
        assert abs(result.total_gross_withdrawn_dkk - expected_total) < Decimal("0.02")

    def test_bridge_config_invalid_cost_basis_above_balance(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            BridgeConfig(
                starting_balance_dkk=Decimal("1000000"),
                cost_basis_dkk=Decimal("1500000"),  # > starting_balance
                horizon_months=120,
                gross_annual_return_rate=Decimal("0.10"),
                annual_expense_ratio=Decimal("0.001"),
                account_type="frie_midler",
                tax_regime="realisation",
                aktieindkomst_threshold_dkk=Decimal("61900"),
            )

    def test_bridge_monthly_flows_length(self) -> None:
        cfg = BridgeConfig(
            starting_balance_dkk=Decimal("500000"),
            cost_basis_dkk=Decimal("500000"),
            horizon_months=24,
            gross_annual_return_rate=Decimal("0.08"),
            annual_expense_ratio=Decimal("0.001"),
            account_type="ask",
            tax_regime="lager",
            aktieindkomst_threshold_dkk=Decimal("61900"),
        )
        result = compute_bridge_pmt(cfg)
        assert len(result.monthly_flows) == 24

    def test_total_wipe_out_net_rate_rejected(self) -> None:
        """A net rate ≤ -100 % cannot compound — must raise."""
        cfg = BridgeConfig(
            starting_balance_dkk=Decimal("1000000"),
            cost_basis_dkk=Decimal("1000000"),
            horizon_months=120,
            gross_annual_return_rate=Decimal("-0.5"),
            annual_expense_ratio=Decimal("0.5"),
            account_type="frie_midler",
            tax_regime="lager",
            aktieindkomst_threshold_dkk=Decimal("61900"),
        )
        with pytest.raises(LiquidDepotError, match="net rate"):
            compute_bridge_pmt(cfg)

    def test_realisation_progressive_tax_annual_basis(self) -> None:
        """Realisation withdrawal tax must respect annual progressive bracket.

        With a 100 % gain fraction (cost_basis=0) and a horizon long enough
        for annual realised gains to exceed the 27 % threshold, the average
        embedded tax rate must exceed 27 % — the per-withdrawal threshold
        application would falsely cap it at 27 %.
        """
        cfg = BridgeConfig(
            starting_balance_dkk=Decimal("3000000"),
            cost_basis_dkk=Decimal("0"),  # 100 % gain fraction
            horizon_months=120,
            gross_annual_return_rate=Decimal("0.07"),
            annual_expense_ratio=Decimal("0.001"),
            account_type="frie_midler",
            tax_regime="realisation",
            aktieindkomst_threshold_dkk=Decimal("61900"),
        )
        result = compute_bridge_pmt(cfg)
        # Annual realised gains will be far above 61 900 DKK, so average
        # effective tax rate must be between 27 % and 42 % (closer to 42 %).
        avg_tax_rate = result.total_tax_paid_dkk / result.total_gross_withdrawn_dkk
        assert avg_tax_rate > Decimal("0.27")
        assert avg_tax_rate < Decimal("0.42")

    def test_realisation_low_gain_stays_in_27_bracket(self) -> None:
        """If annual realised gain stays under the threshold, tax rate ≈ 27 %.

        Tiny portfolio with low cost-basis spread: total annual gain portion
        stays in the 27 % low bracket, so average effective tax on gain
        should be ≈ 27 %.
        """
        cfg = BridgeConfig(
            starting_balance_dkk=Decimal("200000"),
            cost_basis_dkk=Decimal("0"),
            horizon_months=120,
            gross_annual_return_rate=Decimal("0.05"),
            annual_expense_ratio=Decimal("0.001"),
            account_type="frie_midler",
            tax_regime="realisation",
            aktieindkomst_threshold_dkk=Decimal("61900"),
        )
        result = compute_bridge_pmt(cfg)
        avg_tax_rate = result.total_tax_paid_dkk / result.total_gross_withdrawn_dkk
        # Annual gain ≈ 24 000 DKK — well under threshold, expect 27 % bracket
        assert avg_tax_rate < Decimal("0.30")


# ─────────────────────────────────────────────────────────────────────────────
# Strategy comparison
# ─────────────────────────────────────────────────────────────────────────────


class TestCompareLiquidStrategies:
    """Verify that the comparison helper returns correct rankings."""

    def _profiles(self) -> list[FundProfile]:
        return [
            FundProfile(
                label="iShares MSCI World IT (ASK)",
                isin="IE00BJ5JNY98",
                account_type="ask",
                tax_regime="lager",
                gross_annual_return_rate=Decimal("0.10"),
                annual_expense_ratio=Decimal("0.0012"),
                tax_source="depot",
            ),
            FundProfile(
                label="Sparinvest Globale Aktier (frie midler Lager)",
                isin="DK0060747822",
                account_type="frie_midler",
                tax_regime="lager",
                gross_annual_return_rate=Decimal("0.10"),
                annual_expense_ratio=Decimal("0.0049"),
                tax_source="depot",
            ),
            FundProfile(
                label="Danske Invest Teknologi (frie midler Realisation)",
                isin="DK0010263052",
                account_type="frie_midler",
                tax_regime="realisation",
                gross_annual_return_rate=Decimal("0.10"),
                annual_expense_ratio=Decimal("0.0049"),
                annual_dividend_yield=Decimal("0.005"),
                tax_source="depot",
            ),
        ]

    def test_returns_one_row_per_profile(self) -> None:
        profiles = self._profiles()
        rows = compare_liquid_strategies(
            profiles,
            opening_balance_dkk=Decimal("200000"),
            ask_lifetime_deposits_dkk=Decimal("100000"),
            monthly_contribution_dkk=Decimal("10000"),
            base_year=2024,
            horizon_years=10,
        )
        assert len(rows) == len(profiles)

    def test_sorted_by_terminal_balance_descending(self) -> None:
        profiles = self._profiles()
        rows = compare_liquid_strategies(
            profiles,
            opening_balance_dkk=Decimal("200000"),
            ask_lifetime_deposits_dkk=Decimal("100000"),
            monthly_contribution_dkk=Decimal("10000"),
            base_year=2024,
            horizon_years=10,
        )
        balances = [r.terminal_balance_dkk for r in rows]
        assert balances == sorted(balances, reverse=True)

    def test_lower_aop_wins_ceteris_paribus(self) -> None:
        """Higher ÅOP should result in lower terminal balance, all else equal."""
        profiles = [
            FundProfile(
                label="Low ÅOP",
                isin="IE00000000001",
                account_type="frie_midler",
                tax_regime="lager",
                gross_annual_return_rate=Decimal("0.10"),
                annual_expense_ratio=Decimal("0.0010"),
                tax_source="depot",
            ),
            FundProfile(
                label="High ÅOP",
                isin="IE00000000002",
                account_type="frie_midler",
                tax_regime="lager",
                gross_annual_return_rate=Decimal("0.10"),
                annual_expense_ratio=Decimal("0.0100"),
                tax_source="depot",
            ),
        ]
        rows = compare_liquid_strategies(
            profiles,
            opening_balance_dkk=Decimal("300000"),
            ask_lifetime_deposits_dkk=Decimal("0"),
            monthly_contribution_dkk=Decimal("5000"),
            base_year=2024,
            horizon_years=15,
        )
        assert rows[0].label == "Low ÅOP"
        assert rows[0].terminal_balance_dkk > rows[1].terminal_balance_dkk

    def test_all_rows_have_positive_effective_rate_with_positive_return(self) -> None:
        profiles = self._profiles()
        rows = compare_liquid_strategies(
            profiles,
            opening_balance_dkk=Decimal("100000"),
            ask_lifetime_deposits_dkk=Decimal("80000"),
            monthly_contribution_dkk=Decimal("0"),
            base_year=2024,
            horizon_years=5,
        )
        for row in rows:
            assert row.effective_net_annual_rate > Decimal("0")

    def test_all_rows_are_strategy_comparison_row_instances(self) -> None:
        profiles = self._profiles()
        rows = compare_liquid_strategies(
            profiles,
            opening_balance_dkk=Decimal("100000"),
            ask_lifetime_deposits_dkk=Decimal("80000"),
            monthly_contribution_dkk=Decimal("5000"),
            base_year=2024,
            horizon_years=5,
        )
        for row in rows:
            assert isinstance(row, StrategyComparisonRow)


# ─────────────────────────────────────────────────────────────────────────────
# Integration test: accumulation → bridge pipeline
# ─────────────────────────────────────────────────────────────────────────────


class TestAccumulationToBridgePipeline:
    """Full pipeline: accumulate for N years, then deplete over M months."""

    def test_frie_lager_pipeline(self) -> None:
        """Accumulate 10 years, bridge over 120 months, final balance ≈ 0."""
        acc_cfg = _frie_lager_config(
            opening="200000",
            annual_contribution="180000",  # 15 000/month
            gross_rate="0.10",
            aop="0.0012",
            tax_source="depot",
        )
        acc_proj = project_liquid(acc_cfg, base_year=2024, horizon_years=10)
        terminal = acc_proj.terminal_balance_dkk()

        bridge_cfg = BridgeConfig(
            starting_balance_dkk=terminal,
            cost_basis_dkk=terminal,  # lager: no deferred gain
            horizon_months=120,
            gross_annual_return_rate=Decimal("0.08"),  # conservative for drawdown
            annual_expense_ratio=Decimal("0.0012"),
            account_type="frie_midler",
            tax_regime="lager",
            aktieindkomst_threshold_dkk=Decimal("61900"),
        )
        bridge_result = compute_bridge_pmt(bridge_cfg)
        tolerance = terminal * Decimal("0.005")
        assert abs(bridge_result.final_balance_dkk) < tolerance
        assert bridge_result.monthly_gross_withdrawal_dkk > Decimal("0")

    def test_realisation_pipeline(self) -> None:
        """Accumulate realisation account 10 years, bridge with correct cost basis."""
        acc_cfg = _frie_realisation_config(
            opening="200000",
            annual_contribution="180000",
            gross_rate="0.10",
            aop="0.0049",
            dividend_yield="0.005",
            tax_source="depot",
        )
        acc_proj = project_liquid(acc_cfg, base_year=2024, horizon_years=10)
        terminal = acc_proj.terminal_balance_dkk()
        gain_frac = acc_proj.terminal_gain_fraction
        cost_basis = terminal * (Decimal("1") - gain_frac)

        bridge_cfg = BridgeConfig(
            starting_balance_dkk=terminal,
            cost_basis_dkk=cost_basis,
            horizon_months=120,
            gross_annual_return_rate=Decimal("0.08"),
            annual_expense_ratio=Decimal("0.0049"),
            account_type="frie_midler",
            tax_regime="realisation",
            aktieindkomst_threshold_dkk=Decimal("61900"),
        )
        bridge_result = compute_bridge_pmt(bridge_cfg)
        tolerance = terminal * Decimal("0.005")
        assert abs(bridge_result.final_balance_dkk) < tolerance
