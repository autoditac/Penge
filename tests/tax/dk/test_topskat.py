"""Tests for penge.tax.dk.topskat — Topskat exposure check (#129).

All fixtures are synthetic; no real financial data is used.
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal

import pytest

from penge.sim.payout import PayoutConfig, compute_payout
from penge.tax.dk.rates import DK_TOPSKAT_RATE, DK_TOPSKAT_THRESHOLD_DKK
from penge.tax.dk.topskat import (
    TopskatError,
    TopskatWarning,
    check_topskat_exposure,
    topskat_from_payout,
)

# ---------------------------------------------------------------------------
# Below threshold — no Topskat
# ---------------------------------------------------------------------------


class TestBelowThreshold:
    def test_income_zero_not_in_topskat(self) -> None:
        w = check_topskat_exposure(Decimal("0"))
        assert w.in_topskat is False
        assert w.estimated_topskat_dkk == Decimal("0.00")
        assert w.income_above_threshold_dkk == Decimal("0.00")

    def test_income_just_below_threshold(self) -> None:
        w = check_topskat_exposure(DK_TOPSKAT_THRESHOLD_DKK - Decimal("1"))
        assert w.in_topskat is False
        assert w.estimated_topskat_dkk == Decimal("0.00")

    def test_income_at_threshold_not_in_topskat(self) -> None:
        w = check_topskat_exposure(DK_TOPSKAT_THRESHOLD_DKK)
        assert w.in_topskat is False
        assert w.income_above_threshold_dkk == Decimal("0.00")

    def test_no_suggestion_below_threshold(self) -> None:
        w = check_topskat_exposure(Decimal("400000"))
        assert w.suggestion == ""


# ---------------------------------------------------------------------------
# At and above threshold
# ---------------------------------------------------------------------------


class TestAboveThreshold:
    def test_income_just_above_threshold(self) -> None:
        income = DK_TOPSKAT_THRESHOLD_DKK + Decimal("1")
        w = check_topskat_exposure(income)
        assert w.in_topskat is True
        assert w.income_above_threshold_dkk == Decimal("1.00")
        assert w.estimated_topskat_dkk == (Decimal("1") * DK_TOPSKAT_RATE).quantize(Decimal("0.01"))

    def test_topskat_rate_correct(self) -> None:
        excess = Decimal("100000")
        w = check_topskat_exposure(DK_TOPSKAT_THRESHOLD_DKK + excess)
        assert w.estimated_topskat_dkk == Decimal("15000.00")  # 15% of 100,000

    def test_threshold_stored_in_result(self) -> None:
        w = check_topskat_exposure(Decimal("700000"))
        assert w.topskat_threshold_dkk == DK_TOPSKAT_THRESHOLD_DKK

    def test_income_stored_in_result(self) -> None:
        w = check_topskat_exposure(Decimal("700000"))
        assert w.annual_pension_income_dkk == Decimal("700000.00")

    def test_suggestion_present_above_threshold(self) -> None:
        w = check_topskat_exposure(Decimal("700000"))
        assert w.suggestion != ""

    def test_high_excess_suggestion_contains_aldersforsikring(self) -> None:
        # More than double threshold → most aggressive suggestion
        w = check_topskat_exposure(DK_TOPSKAT_THRESHOLD_DKK * Decimal("3"))
        assert "Aldersforsikring" in w.suggestion

    def test_moderate_excess_suggestion(self) -> None:
        # ~40 % over threshold → combined suggestion
        income = DK_TOPSKAT_THRESHOLD_DKK * Decimal("1.4")
        w = check_topskat_exposure(income)
        assert "Aldersforsikring" in w.suggestion

    def test_small_excess_suggests_drawdown_extension(self) -> None:
        # ~10 % over threshold → simple drawdown extension suggestion
        income = DK_TOPSKAT_THRESHOLD_DKK * Decimal("1.1")
        w = check_topskat_exposure(income)
        assert "Ratepension" in w.suggestion


# ---------------------------------------------------------------------------
# User's actual scenario: ~18M DKK pension balance
# ---------------------------------------------------------------------------


class TestUserScenario:
    """Representative scenario from the issue: ~18M DKK pension at retirement.

    Monthly income approx 75 000-90 000 DKK, annual approx 900 000-1 080 000 DKK.
    This is well above the 588 900 DKK threshold.
    """

    def test_900k_annual_in_topskat(self) -> None:
        w = check_topskat_exposure(Decimal("900000"))
        assert w.in_topskat is True
        assert w.income_above_threshold_dkk > Decimal("0")

    def test_900k_topskat_amount(self) -> None:
        # excess = 900,000 - 588,900 = 311,100 → topskat = 46,665
        w = check_topskat_exposure(Decimal("900000"))
        assert w.estimated_topskat_dkk == Decimal("46665.00")

    def test_1080k_annual_in_topskat(self) -> None:
        w = check_topskat_exposure(Decimal("1080000"))
        assert w.in_topskat is True
        assert w.estimated_topskat_dkk > Decimal("0")


# ---------------------------------------------------------------------------
# Configurable threshold
# ---------------------------------------------------------------------------


class TestConfigurableThreshold:
    def test_custom_threshold_used(self) -> None:
        w = check_topskat_exposure(Decimal("600000"), topskat_threshold_dkk=Decimal("650000"))
        assert w.in_topskat is False

    def test_custom_threshold_lower_gives_exposure(self) -> None:
        w = check_topskat_exposure(Decimal("500000"), topskat_threshold_dkk=Decimal("400000"))
        assert w.in_topskat is True
        assert w.income_above_threshold_dkk == Decimal("100000.00")


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_negative_income_raises(self) -> None:
        with pytest.raises(TopskatError, match="annual_pension_income_dkk must be >= 0"):
            check_topskat_exposure(Decimal("-1"))

    def test_zero_threshold_raises(self) -> None:
        with pytest.raises(TopskatError, match="topskat_threshold_dkk must be > 0"):
            check_topskat_exposure(Decimal("100000"), topskat_threshold_dkk=Decimal("0"))

    def test_negative_threshold_raises(self) -> None:
        with pytest.raises(TopskatError, match="topskat_threshold_dkk must be > 0"):
            check_topskat_exposure(Decimal("100000"), topskat_threshold_dkk=Decimal("-1"))

    def test_nan_income_raises(self) -> None:
        with pytest.raises(TopskatError, match="must be a finite Decimal"):
            check_topskat_exposure(Decimal("NaN"))

    def test_infinity_income_raises(self) -> None:
        with pytest.raises(TopskatError, match="must be a finite Decimal"):
            check_topskat_exposure(Decimal("Infinity"))

    def test_nan_threshold_raises(self) -> None:
        with pytest.raises(TopskatError, match="must be a finite Decimal"):
            check_topskat_exposure(Decimal("500000"), topskat_threshold_dkk=Decimal("NaN"))

    def test_nan_eur_per_dkk_raises(self) -> None:
        proj = compute_payout(_make_payout_cfg())
        with pytest.raises(TopskatError, match="must be a finite Decimal"):
            topskat_from_payout(proj, eur_per_dkk=Decimal("NaN"))

    def test_infinity_eur_per_dkk_raises(self) -> None:
        proj = compute_payout(_make_payout_cfg())
        with pytest.raises(TopskatError, match="must be a finite Decimal"):
            topskat_from_payout(proj, eur_per_dkk=Decimal("Infinity"))


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


class TestImmutability:
    def test_warning_is_frozen(self) -> None:
        w = check_topskat_exposure(Decimal("700000"))
        with pytest.raises(dataclasses.FrozenInstanceError):
            w.in_topskat = False  # type: ignore[misc]  # intentionally mutating frozen dataclass to verify FrozenInstanceError


# ---------------------------------------------------------------------------
# Integration: topskat_from_payout
# ---------------------------------------------------------------------------


def _make_payout_cfg(**kwargs: object) -> PayoutConfig:
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
    return PayoutConfig(**defaults)  # type: ignore[arg-type]  # dict[str, object] used for test convenience


class TestTopskatFromPayout:
    def test_converts_eur_to_dkk_correctly(self) -> None:
        # 1M EUR balance, 70% livrente @ factor 4000
        # monthly_livrente = 700,000 * 4000 / 1,000,000 = 2,800 EUR/month
        # ratepension = 250,000 / 180 ≈ 1,388.89 EUR/month
        # total_monthly ≈ 4,188.89 EUR → annual ≈ 50,267 EUR
        # At eur_per_dkk=0.1341: annual_dkk ≈ 50,267 / 0.1341 ≈ 374,847 DKK
        # Well below threshold → not in topskat
        proj = compute_payout(_make_payout_cfg())
        w = topskat_from_payout(proj, eur_per_dkk=Decimal("0.1341"))
        assert isinstance(w, TopskatWarning)
        # Low balance → below threshold
        assert w.in_topskat is False

    def test_large_balance_above_threshold(self) -> None:
        # 18M DKK pension ≈ 2,413,870 EUR at 0.1341
        balance_eur = Decimal("18000000") * Decimal("0.1341")
        proj = compute_payout(_make_payout_cfg(pension_balance_eur=balance_eur))
        w = topskat_from_payout(proj, eur_per_dkk=Decimal("0.1341"))
        assert w.in_topskat is True

    def test_zero_eur_per_dkk_raises(self) -> None:
        proj = compute_payout(_make_payout_cfg())
        with pytest.raises(TopskatError, match="eur_per_dkk must be > 0"):
            topskat_from_payout(proj, eur_per_dkk=Decimal("0"))
