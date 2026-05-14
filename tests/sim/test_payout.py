"""Tests for penge.sim.payout — decumulation payout modelling.

All fixtures are synthetic; no real financial data is used.
"""

from __future__ import annotations

from decimal import Decimal

import pydantic
import pytest

from penge.sim.cashflow import (
    CashflowConfig,
    PensionAccrualRule,
    SalaryRule,
    project,
)
from penge.sim.payout import (  # noqa: F401
    PayoutConfig,
    PayoutError,
    PayoutProjection,
    compute_payout,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cfg(**kwargs: object) -> PayoutConfig:
    """Build a PayoutConfig with minimal required fields, overriding with kwargs."""
    defaults: dict[str, object] = {
        "entity": "alice",
        "pension_balance_eur": Decimal("1000000"),
        "retirement_age": 67,
        "livrente_fraction": Decimal("0.70"),
        "ratepension_fraction": Decimal("0.25"),
        "ratepension_years": 15,
        "annuity_factor": Decimal("4000"),
        "growth_rate_during_payout": Decimal("0"),
    }
    defaults.update(kwargs)
    return PayoutConfig(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Capital split
# ---------------------------------------------------------------------------


class TestCapitalSplit:
    def test_three_tranches_sum_to_balance(self) -> None:
        proj = compute_payout(_cfg())
        assert (
            proj.livrente_capital_eur
            + proj.ratepension_capital_eur
            + proj.aldersforsikring_lump_sum_eur
        ) == proj.config.pension_balance_eur

    def test_livrente_capital(self) -> None:
        proj = compute_payout(_cfg(pension_balance_eur=Decimal("2000000")))
        assert proj.livrente_capital_eur == Decimal("1400000.00")  # 70%

    def test_ratepension_capital(self) -> None:
        proj = compute_payout(_cfg(pension_balance_eur=Decimal("2000000")))
        assert proj.ratepension_capital_eur == Decimal("500000.00")  # 25%

    def test_aldersforsikring_is_remainder(self) -> None:
        proj = compute_payout(_cfg(pension_balance_eur=Decimal("2000000")))
        # 5% = 100,000
        assert proj.aldersforsikring_lump_sum_eur == Decimal("100000.00")

    def test_zero_balance_gives_zero_payouts(self) -> None:
        proj = compute_payout(_cfg(pension_balance_eur=Decimal("0")))
        assert proj.monthly_livrente_eur == Decimal("0.00")
        assert proj.monthly_ratepension_eur == Decimal("0.00")
        assert proj.total_monthly_gross_eur == Decimal("0.00")

    def test_all_livrente_zero_ratepension(self) -> None:
        proj = compute_payout(
            _cfg(livrente_fraction=Decimal("1"), ratepension_fraction=Decimal("0"))
        )
        assert proj.ratepension_capital_eur == Decimal("0.00")
        assert proj.aldersforsikring_lump_sum_eur == Decimal("0.00")

    def test_all_ratepension_zero_livrente(self) -> None:
        proj = compute_payout(
            _cfg(livrente_fraction=Decimal("0"), ratepension_fraction=Decimal("1"))
        )
        assert proj.livrente_capital_eur == Decimal("0.00")
        assert proj.monthly_livrente_eur == Decimal("0.00")

    def test_fractions_sum_exactly_one(self) -> None:
        """livrente + ratepension = 1 ⟹ aldersforsikring = 0."""
        proj = compute_payout(
            _cfg(livrente_fraction=Decimal("0.60"), ratepension_fraction=Decimal("0.40"))
        )
        assert proj.aldersforsikring_lump_sum_eur == Decimal("0.00")


# ---------------------------------------------------------------------------
# Livrente annuity
# ---------------------------------------------------------------------------


class TestLivrente:
    def test_factor_4000_on_1m_capital(self) -> None:
        # Livrente capital = 1,000,000 * 0.70 = 700,000
        # monthly = 700,000 * 4000 / 1,000,000 = 2,800
        proj = compute_payout(_cfg(pension_balance_eur=Decimal("1000000")))
        assert proj.monthly_livrente_eur == Decimal("2800.00")

    def test_higher_factor_gives_higher_payout(self) -> None:
        low = compute_payout(_cfg(annuity_factor=Decimal("3800")))
        high = compute_payout(_cfg(annuity_factor=Decimal("4200")))
        assert high.monthly_livrente_eur > low.monthly_livrente_eur

    def test_larger_balance_proportional_payout(self) -> None:
        half = compute_payout(_cfg(pension_balance_eur=Decimal("500000")))
        full = compute_payout(_cfg(pension_balance_eur=Decimal("1000000")))
        assert full.monthly_livrente_eur == 2 * half.monthly_livrente_eur

    def test_small_factor_precision(self) -> None:
        # 18,000,000 balance * 0.70 = 12,600,000 livrente capital
        # monthly = 12,600,000 * 4100 / 1,000,000 = 51,660
        proj = compute_payout(
            _cfg(
                pension_balance_eur=Decimal("18000000"),
                annuity_factor=Decimal("4100"),
            )
        )
        assert proj.monthly_livrente_eur == Decimal("51660.00")


# ---------------------------------------------------------------------------
# Ratepension PMT
# ---------------------------------------------------------------------------


class TestRatepension:
    def test_zero_growth_level_drawdown(self) -> None:
        # 250,000 capital over 15 years (180 months) = 1,388.89
        proj = compute_payout(
            _cfg(
                pension_balance_eur=Decimal("1000000"),
                ratepension_fraction=Decimal("0.25"),
                ratepension_years=15,
                growth_rate_during_payout=Decimal("0"),
                livrente_fraction=Decimal("0"),
            )
        )
        expected = (Decimal("250000") / Decimal("180")).quantize(
            Decimal("0.01"), rounding=__import__("decimal").ROUND_HALF_EVEN
        )
        assert proj.monthly_ratepension_eur == expected

    def test_zero_growth_10_years(self) -> None:
        # 300,000 / 120 months = 2,500.00
        proj = compute_payout(
            _cfg(
                pension_balance_eur=Decimal("1200000"),
                ratepension_fraction=Decimal("0.25"),
                ratepension_years=10,
                growth_rate_during_payout=Decimal("0"),
                livrente_fraction=Decimal("0"),
            )
        )
        assert proj.monthly_ratepension_eur == Decimal("2500.00")

    def test_growth_increases_monthly_pmt(self) -> None:
        """Positive residual growth ⟹ higher monthly payment than flat drawdown."""
        flat = compute_payout(_cfg(ratepension_years=20, growth_rate_during_payout=Decimal("0")))
        growing = compute_payout(
            _cfg(ratepension_years=20, growth_rate_during_payout=Decimal("0.04"))
        )
        assert growing.monthly_ratepension_eur > flat.monthly_ratepension_eur

    def test_longer_period_lower_pmt(self) -> None:
        short = compute_payout(_cfg(ratepension_years=10))
        long_ = compute_payout(_cfg(ratepension_years=30))
        assert short.monthly_ratepension_eur > long_.monthly_ratepension_eur

    def test_pmt_pv_round_trips(self) -> None:
        """PV of all payments ~= initial capital (within rounding tolerance)."""
        annual_rate = Decimal("0.05")
        r_float = float(annual_rate + 1) ** (1 / 12) - 1
        r = Decimal(str(r_float))
        n = 20 * 12  # 240 months
        capital = Decimal("300000")

        proj = compute_payout(
            _cfg(
                ratepension_fraction=Decimal("0.30"),
                pension_balance_eur=capital / Decimal("0.30"),
                ratepension_years=20,
                growth_rate_during_payout=annual_rate,
                livrente_fraction=Decimal("0"),
            )
        )
        pmt = proj.monthly_ratepension_eur

        # Sum PV of payments
        pv = sum(pmt / (1 + r) ** k for k in range(1, n + 1))
        assert abs(pv - capital) < Decimal("6")  # within 6 EUR (240 payments x 2-dp rounding)

    def test_zero_ratepension_fraction(self) -> None:
        proj = compute_payout(_cfg(ratepension_fraction=Decimal("0")))
        assert proj.monthly_ratepension_eur == Decimal("0.00")


# ---------------------------------------------------------------------------
# Total monthly gross
# ---------------------------------------------------------------------------


class TestTotalMonthly:
    def test_total_is_sum_of_components(self) -> None:
        proj = compute_payout(_cfg())
        assert proj.total_monthly_gross_eur == (
            proj.monthly_livrente_eur + proj.monthly_ratepension_eur
        )

    def test_both_zero_when_balance_zero(self) -> None:
        proj = compute_payout(_cfg(pension_balance_eur=Decimal("0")))
        assert proj.total_monthly_gross_eur == Decimal("0.00")


# ---------------------------------------------------------------------------
# PayoutConfig validation
# ---------------------------------------------------------------------------


class TestPayoutConfigValidation:
    def test_negative_balance_rejected(self) -> None:
        with pytest.raises(pydantic.ValidationError, match="pension_balance_eur must be >= 0"):
            _cfg(pension_balance_eur=Decimal("-1"))

    def test_retirement_age_below_60_rejected(self) -> None:
        with pytest.raises(pydantic.ValidationError, match="retirement_age must be >= 60"):
            _cfg(retirement_age=59)

    def test_fractions_exceed_one_rejected(self) -> None:
        with pytest.raises(
            pydantic.ValidationError,
            match=r"livrente_fraction.*ratepension_fraction must be <= 1",
        ):
            _cfg(livrente_fraction=Decimal("0.70"), ratepension_fraction=Decimal("0.40"))

    def test_negative_livrente_fraction_rejected(self) -> None:
        with pytest.raises(pydantic.ValidationError, match="livrente_fraction must be >= 0"):
            _cfg(livrente_fraction=Decimal("-0.1"))

    def test_negative_ratepension_fraction_rejected(self) -> None:
        with pytest.raises(pydantic.ValidationError, match="ratepension_fraction must be >= 0"):
            _cfg(ratepension_fraction=Decimal("-0.1"))

    def test_ratepension_years_below_10_rejected(self) -> None:
        with pytest.raises(
            pydantic.ValidationError,
            match=r"ratepension_years must be in \[10, 30\]",
        ):
            _cfg(ratepension_years=9)

    def test_ratepension_years_above_30_rejected(self) -> None:
        with pytest.raises(
            pydantic.ValidationError,
            match=r"ratepension_years must be in \[10, 30\]",
        ):
            _cfg(ratepension_years=31)

    def test_zero_annuity_factor_rejected(self) -> None:
        with pytest.raises(pydantic.ValidationError, match="annuity_factor must be > 0"):
            _cfg(annuity_factor=Decimal("0"))

    def test_growth_rate_le_minus_one_rejected(self) -> None:
        with pytest.raises(
            pydantic.ValidationError,
            match="growth_rate_during_payout must be > -1",
        ):
            _cfg(growth_rate_during_payout=Decimal("-1"))

    def test_coerce_float_inputs(self) -> None:
        """Pydantic coercion: float inputs are accepted and converted to Decimal."""
        cfg = _cfg(pension_balance_eur=1_000_000.0, annuity_factor=4000.0)  # type: ignore[arg-type]
        assert cfg.pension_balance_eur == Decimal("1000000")

    def test_fractions_exactly_one_accepted(self) -> None:
        cfg = _cfg(livrente_fraction=Decimal("0.75"), ratepension_fraction=Decimal("0.25"))
        proj = compute_payout(cfg)
        assert proj.aldersforsikring_lump_sum_eur == Decimal("0.00")

    def test_zero_balance_accepted(self) -> None:
        cfg = _cfg(pension_balance_eur=Decimal("0"))
        assert cfg.pension_balance_eur == Decimal("0")


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


class TestImmutability:
    def test_config_is_frozen(self) -> None:
        cfg = _cfg()
        with pytest.raises(pydantic.ValidationError):
            cfg.retirement_age = 68  # type: ignore[misc]

    def test_projection_is_frozen(self) -> None:
        proj = compute_payout(_cfg())
        with pytest.raises(pydantic.ValidationError):
            proj.monthly_livrente_eur = Decimal("0")  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Integration: CashflowProjection.payout_at()
# ---------------------------------------------------------------------------


class TestCashflowIntegration:
    def _build_projection(self) -> object:
        """Build a minimal CashflowProjection for integration testing."""
        cfg = CashflowConfig(
            base_year=2025,
            horizon_years=10,
            inflation_rate=Decimal("0.02"),
            eur_per_dkk=Decimal("0.1341"),
            salaries=(
                SalaryRule(
                    entity="alice",
                    gross_annual=Decimal("60000"),
                    currency="EUR",
                ),
            ),
            contributions=(),
            pension_rules=(
                PensionAccrualRule(
                    entity="alice",
                    kind="dc_fraction",
                    dc_fraction=Decimal("0.20"),
                    vesting_year=2055,
                ),
            ),
            pension_opening_balances={"alice": Decimal("200000")},
            pension_market_return_rate=Decimal("0.06"),
            pal_skat_rate=Decimal("0.154"),
        )
        return project(cfg)

    def test_payout_at_uses_projected_balance(self) -> None:
        proj = self._build_projection()
        assert hasattr(proj, "payout_at")

        # The config's pension_balance_eur should be overridden by the projection
        dummy_balance = Decimal("999")  # will be ignored
        payout_cfg = PayoutConfig(
            entity="alice",
            pension_balance_eur=dummy_balance,
            retirement_age=67,
            livrente_fraction=Decimal("0.70"),
            ratepension_fraction=Decimal("0.25"),
            ratepension_years=15,
            annuity_factor=Decimal("4000"),
        )

        year_2035 = 2025 + 10
        payout = proj.payout_at(year_2035, payout_cfg)  # type: ignore[union-attr]

        # The projected balance at year_2035 for "alice" should differ from dummy_balance
        flows = proj.by_entity("alice")  # type: ignore[union-attr]
        last_flow = next(f for f in flows if f.year == year_2035)
        assert payout.config.pension_balance_eur == last_flow.cumulative_pension_eur
        assert payout.config.pension_balance_eur != dummy_balance

    def test_payout_at_unknown_year_raises(self) -> None:
        proj = self._build_projection()
        payout_cfg = PayoutConfig(
            entity="alice",
            pension_balance_eur=Decimal("1"),
            retirement_age=67,
            livrente_fraction=Decimal("0.70"),
            ratepension_fraction=Decimal("0.25"),
            ratepension_years=15,
            annuity_factor=Decimal("4000"),
        )
        with pytest.raises(KeyError, match="9999"):
            proj.payout_at(9999, payout_cfg)  # type: ignore[union-attr]

    def test_payout_at_unknown_entity_raises(self) -> None:
        proj = self._build_projection()
        payout_cfg = PayoutConfig(
            entity="unknown_entity",
            pension_balance_eur=Decimal("1"),
            retirement_age=67,
            livrente_fraction=Decimal("0.70"),
            ratepension_fraction=Decimal("0.25"),
            ratepension_years=15,
            annuity_factor=Decimal("4000"),
        )
        with pytest.raises(KeyError, match="unknown_entity"):
            proj.payout_at(2035, payout_cfg)  # type: ignore[union-attr]

    def test_payout_total_positive(self) -> None:
        proj = self._build_projection()
        payout_cfg = PayoutConfig(
            entity="alice",
            pension_balance_eur=Decimal("1"),  # will be overridden
            retirement_age=67,
            livrente_fraction=Decimal("0.70"),
            ratepension_fraction=Decimal("0.25"),
            ratepension_years=20,
            annuity_factor=Decimal("4000"),
            growth_rate_during_payout=Decimal("0.03"),
        )
        payout = proj.payout_at(2035, payout_cfg)  # type: ignore[union-attr]
        assert payout.total_monthly_gross_eur > Decimal("0")
