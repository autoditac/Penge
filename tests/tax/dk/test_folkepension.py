"""Tests for penge.tax.dk.folkepension — Folkepension modregning model (#131).

All fixtures are synthetic; no real financial data is used.
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal

import pytest

from penge.sim.payout import PayoutConfig, compute_payout
from penge.tax.dk.folkepension import (
    FolkepensionConfig,
    FolkepensionError,
    FolkepensionResult,
    compute_folkepension,
    folkepension_age_for_year,
    folkepension_from_payout,
)
from penge.tax.dk.rates import (
    FOLKEPENSION_GRUNDBELOEB_MONTHLY_DKK,
    FOLKEPENSION_TILLAEG_MARRIED_MONTHLY_DKK,
    FOLKEPENSION_TILLAEG_SINGLE_MONTHLY_DKK,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cfg(
    civil_status: str = "single",
    annual_private_pension_income_dkk: Decimal = Decimal("0"),
    folkepension_age: int = 67,
    **kwargs: object,
) -> FolkepensionConfig:
    return FolkepensionConfig(
        civil_status=civil_status,  # type: ignore[arg-type]
        folkepension_age=folkepension_age,
        annual_private_pension_income_dkk=annual_private_pension_income_dkk,
        **kwargs,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# No modregning — income below threshold
# ---------------------------------------------------------------------------


class TestNoModregning:
    def test_zero_income_full_tillaeg_single(self) -> None:
        result = compute_folkepension(_cfg("single", Decimal("0")))
        assert result.tillaeg_after_modregning_dkk == FOLKEPENSION_TILLAEG_SINGLE_MONTHLY_DKK

    def test_zero_income_full_tillaeg_married(self) -> None:
        result = compute_folkepension(_cfg("married", Decimal("0")))
        assert result.tillaeg_after_modregning_dkk == FOLKEPENSION_TILLAEG_MARRIED_MONTHLY_DKK

    def test_zero_income_modregning_is_zero(self) -> None:
        result = compute_folkepension(_cfg())
        assert result.modregning_dkk == Decimal("0.00")

    def test_income_at_threshold_no_modregning(self) -> None:
        result = compute_folkepension(_cfg(annual_private_pension_income_dkk=Decimal("94800")))
        assert result.modregning_dkk == Decimal("0.00")
        assert result.tillaeg_after_modregning_dkk == FOLKEPENSION_TILLAEG_SINGLE_MONTHLY_DKK

    def test_income_below_threshold_no_modregning(self) -> None:
        result = compute_folkepension(_cfg(annual_private_pension_income_dkk=Decimal("50000")))
        assert result.modregning_dkk == Decimal("0.00")


# ---------------------------------------------------------------------------
# Partial modregning
# ---------------------------------------------------------------------------


class TestPartialModregning:
    def test_income_above_threshold_reduces_tillaeg(self) -> None:
        # excess = 200,000 - 94,800 = 105,200
        # annual_modregning = 105,200 * 0.309 = 32,506.80
        # monthly_modregning = 32,506.80 / 12 = 2,708.90
        result = compute_folkepension(_cfg(annual_private_pension_income_dkk=Decimal("200000")))
        assert result.modregning_dkk > Decimal("0")
        assert result.tillaeg_after_modregning_dkk < FOLKEPENSION_TILLAEG_SINGLE_MONTHLY_DKK
        assert result.tillaeg_after_modregning_dkk > Decimal("0")

    def test_modregning_computation_correct(self) -> None:
        # excess = 200,000 - 94,800 = 105,200
        # monthly_modregning = 105,200 * 0.309 / 12 = 2,708.90
        result = compute_folkepension(_cfg(annual_private_pension_income_dkk=Decimal("200000")))
        expected_modregning = (Decimal("105200") * Decimal("0.309") / Decimal("12")).quantize(
            Decimal("0.01")
        )
        assert result.modregning_dkk == expected_modregning

    def test_total_equals_grundbeloeb_plus_tillaeg_after(self) -> None:
        result = compute_folkepension(_cfg(annual_private_pension_income_dkk=Decimal("200000")))
        assert result.total_monthly_dkk == (
            result.grundbeloeb_monthly_dkk + result.tillaeg_after_modregning_dkk
        )

    def test_tillaeg_before_modregning_is_max(self) -> None:
        result = compute_folkepension(_cfg("single", Decimal("200000")))
        assert result.tillaeg_before_modregning_dkk == FOLKEPENSION_TILLAEG_SINGLE_MONTHLY_DKK


# ---------------------------------------------------------------------------
# Full modregning — tillæg zeroed
# ---------------------------------------------------------------------------


class TestFullModregning:
    def test_high_income_zeroes_tillaeg(self) -> None:
        # 900,000 DKK/year is well above the threshold
        result = compute_folkepension(_cfg(annual_private_pension_income_dkk=Decimal("900000")))
        assert result.tillaeg_after_modregning_dkk == Decimal("0.00")

    def test_total_equals_grundbeloeb_when_tillaeg_zeroed(self) -> None:
        result = compute_folkepension(_cfg(annual_private_pension_income_dkk=Decimal("900000")))
        assert result.total_monthly_dkk == result.grundbeloeb_monthly_dkk

    def test_grundbeloeb_always_paid(self) -> None:
        result = compute_folkepension(_cfg(annual_private_pension_income_dkk=Decimal("10000000")))
        assert result.grundbeloeb_monthly_dkk == FOLKEPENSION_GRUNDBELOEB_MONTHLY_DKK
        assert result.total_monthly_dkk == FOLKEPENSION_GRUNDBELOEB_MONTHLY_DKK

    def test_tillaeg_never_negative(self) -> None:
        result = compute_folkepension(_cfg(annual_private_pension_income_dkk=Decimal("10000000")))
        assert result.tillaeg_after_modregning_dkk >= Decimal("0")


# ---------------------------------------------------------------------------
# User's case: ~75,000 DKK/month private income
# ---------------------------------------------------------------------------


class TestUserScenario:
    """Issue requirement: test matching user's case — ~75,000 kr/month → tillæg = 0."""

    def test_900k_annual_single_tillaeg_zeroed(self) -> None:
        # 75,000 DKK/month x 12 = 900,000 DKK/year
        result = compute_folkepension(
            _cfg("single", annual_private_pension_income_dkk=Decimal("900000"))
        )
        assert result.tillaeg_after_modregning_dkk == Decimal("0.00")

    def test_900k_annual_only_grundbeloeb_remains(self) -> None:
        result = compute_folkepension(
            _cfg("single", annual_private_pension_income_dkk=Decimal("900000"))
        )
        assert result.total_monthly_dkk == FOLKEPENSION_GRUNDBELOEB_MONTHLY_DKK

    def test_900k_annual_married_tillaeg_zeroed(self) -> None:
        result = compute_folkepension(
            _cfg("married", annual_private_pension_income_dkk=Decimal("900000"))
        )
        assert result.tillaeg_after_modregning_dkk == Decimal("0.00")


# ---------------------------------------------------------------------------
# Civil status differences
# ---------------------------------------------------------------------------


class TestCivilStatus:
    def test_single_tillaeg_higher_than_married(self) -> None:
        single = compute_folkepension(_cfg("single", Decimal("0")))
        married = compute_folkepension(_cfg("married", Decimal("0")))
        assert single.tillaeg_before_modregning_dkk > married.tillaeg_before_modregning_dkk

    def test_same_income_same_grundbeloeb(self) -> None:
        single = compute_folkepension(_cfg("single", Decimal("100000")))
        married = compute_folkepension(_cfg("married", Decimal("100000")))
        assert single.grundbeloeb_monthly_dkk == married.grundbeloeb_monthly_dkk

    def test_custom_tillaeg_override(self) -> None:
        result = compute_folkepension(
            _cfg(
                tillaeg_max_monthly_dkk=Decimal("10000"),
                annual_private_pension_income_dkk=Decimal("0"),
            )
        )
        assert result.tillaeg_before_modregning_dkk == Decimal("10000.00")


# ---------------------------------------------------------------------------
# Folkepensionsalder schedule
# ---------------------------------------------------------------------------


class TestFolkepensionAgeSchedule:
    def test_2026_is_67(self) -> None:
        assert folkepension_age_for_year(2026) == 67

    def test_2029_is_still_67(self) -> None:
        assert folkepension_age_for_year(2029) == 67

    def test_2030_is_68(self) -> None:
        assert folkepension_age_for_year(2030) == 68

    def test_2034_is_still_68(self) -> None:
        assert folkepension_age_for_year(2034) == 68

    def test_2035_is_69(self) -> None:
        assert folkepension_age_for_year(2035) == 69

    def test_2099_is_69(self) -> None:
        assert folkepension_age_for_year(2099) == 69

    def test_before_schedule_raises(self) -> None:
        with pytest.raises(FolkepensionError):
            folkepension_age_for_year(2000)


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_negative_income_raises(self) -> None:
        with pytest.raises(FolkepensionError, match="annual_private_pension_income_dkk must be"):
            compute_folkepension(_cfg(annual_private_pension_income_dkk=Decimal("-1")))

    def test_negative_grundbeloeb_raises(self) -> None:
        with pytest.raises(FolkepensionError, match="grundbeloeb_monthly_dkk must be >= 0"):
            compute_folkepension(_cfg(grundbeloeb_monthly_dkk=Decimal("-1")))

    def test_modregning_rate_above_one_raises(self) -> None:
        with pytest.raises(FolkepensionError, match="modregning_rate must be in"):
            compute_folkepension(_cfg(modregning_rate=Decimal("1.1")))

    def test_negative_modregning_rate_raises(self) -> None:
        with pytest.raises(FolkepensionError, match="modregning_rate must be in"):
            compute_folkepension(_cfg(modregning_rate=Decimal("-0.1")))

    def test_folkepension_age_below_60_raises(self) -> None:
        with pytest.raises(FolkepensionError, match="folkepension_age must be >= 60"):
            compute_folkepension(_cfg(folkepension_age=59))

    def test_negative_tillaeg_max_raises(self) -> None:
        with pytest.raises(FolkepensionError, match="tillaeg_max_monthly_dkk must be >= 0"):
            compute_folkepension(_cfg(tillaeg_max_monthly_dkk=Decimal("-1")))


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


class TestImmutability:
    def test_result_is_frozen(self) -> None:
        result = compute_folkepension(_cfg())
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.total_monthly_dkk = Decimal("0")  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Integration: folkepension_from_payout
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
    return PayoutConfig(**defaults)  # type: ignore[arg-type]


class TestFolkepensionFromPayout:
    def test_returns_folkepension_result(self) -> None:
        proj = compute_payout(_make_payout_cfg())
        result = folkepension_from_payout(
            proj,
            civil_status="single",
            folkepension_age=67,
            eur_per_dkk=Decimal("0.1341"),
        )
        assert isinstance(result, FolkepensionResult)

    def test_low_balance_keeps_full_tillaeg(self) -> None:
        # Small balance → small annual income → below modregning threshold
        proj = compute_payout(_make_payout_cfg(pension_balance_eur=Decimal("100000")))
        result = folkepension_from_payout(
            proj,
            civil_status="single",
            folkepension_age=67,
            eur_per_dkk=Decimal("0.1341"),
        )
        assert result.tillaeg_after_modregning_dkk == FOLKEPENSION_TILLAEG_SINGLE_MONTHLY_DKK

    def test_large_balance_zeroes_tillaeg(self) -> None:
        # 18M DKK pension → annual income ~900k DKK → tillæg = 0
        balance_eur = Decimal("18000000") * Decimal("0.1341")
        proj = compute_payout(_make_payout_cfg(pension_balance_eur=balance_eur))
        result = folkepension_from_payout(
            proj,
            civil_status="single",
            folkepension_age=67,
            eur_per_dkk=Decimal("0.1341"),
        )
        assert result.tillaeg_after_modregning_dkk == Decimal("0.00")

    def test_zero_eur_per_dkk_raises(self) -> None:
        proj = compute_payout(_make_payout_cfg())
        with pytest.raises(FolkepensionError, match="eur_per_dkk must be > 0"):
            folkepension_from_payout(
                proj,
                civil_status="single",
                folkepension_age=67,
                eur_per_dkk=Decimal("0"),
            )
