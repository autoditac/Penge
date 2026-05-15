"""Tests for penge.tax.dk.constants_meta — freshness checks and metadata quality."""

from __future__ import annotations

from typing import ClassVar

import pytest

from penge.tax.dk.constants_meta import (
    ALL_PLANNING_CONSTANTS,
    ConstantMeta,
    check_freshness,
)


class TestConstantMetaIntegrity:
    """All registered constants have complete, non-empty metadata."""

    def test_all_constants_have_name(self) -> None:
        for meta in ALL_PLANNING_CONSTANTS:
            assert meta.name, f"Empty name for constant {meta.constant!r}"

    def test_all_constants_have_constant_attr(self) -> None:
        for meta in ALL_PLANNING_CONSTANTS:
            assert meta.constant, f"Empty constant for {meta.name!r}"

    def test_all_constants_have_module(self) -> None:
        for meta in ALL_PLANNING_CONSTANTS:
            assert meta.module, f"Empty module for {meta.name!r}"

    def test_all_constants_have_source_url(self) -> None:
        for meta in ALL_PLANNING_CONSTANTS:
            assert meta.source_url, f"Empty source_url for {meta.name!r}"
            assert meta.source_url.startswith(
                "http"
            ), f"source_url for {meta.name!r} does not look like a URL"

    def test_all_constants_have_source_year(self) -> None:
        for meta in ALL_PLANNING_CONSTANTS:
            assert meta.source_year >= 2024, (
                f"{meta.name!r} has source_year={meta.source_year}, "
                "expected 2024 or later"
            )

    def test_all_constants_have_unit(self) -> None:
        for meta in ALL_PLANNING_CONSTANTS:
            assert meta.unit, f"Empty unit for {meta.name!r}"

    def test_all_constants_have_publisher(self) -> None:
        for meta in ALL_PLANNING_CONSTANTS:
            assert meta.publisher, f"Empty publisher for {meta.name!r}"

    def test_folkepension_publisher_is_not_skat(self) -> None:
        for meta in ALL_PLANNING_CONSTANTS:
            if "folkepension" in meta.constant.lower() or "folkepension" in meta.name.lower():
                assert meta.publisher != "SKAT", (
                    f"{meta.name!r} should have publisher 'Ankestyrelsen' or "
                    f"'Folkepensionsloven', not 'SKAT'"
                )

    def test_constant_names_are_unique(self) -> None:
        names = [m.name for m in ALL_PLANNING_CONSTANTS]
        assert len(names) == len(set(names)), "Duplicate constant names in registry"

    def test_constant_attrs_are_unique(self) -> None:
        attrs = [m.constant for m in ALL_PLANNING_CONSTANTS]
        assert len(attrs) == len(set(attrs)), "Duplicate constant attrs in registry"


class TestCheckFreshness:
    """check_freshness returns the expected stale constants."""

    def test_all_fresh_for_current_year(self) -> None:
        """All constants should be fresh as of their registered source years."""
        # Identify the maximum source year in the registry, then check that
        # no constant is stale from the perspective of that year.
        max_year = max(m.source_year for m in ALL_PLANNING_CONSTANTS)
        stale = check_freshness(current_year=max_year)
        assert stale == [], (
            f"Constants stale relative to max_year={max_year}: "
            + ", ".join(m.name for m in stale)
        )

    def test_stale_constants_detected(self) -> None:
        """Constants with old source years are flagged."""
        # Ask for freshness check as if it's year 2030 with max_age=1.
        # All current constants (source_year 2025/2026) should be stale.
        stale = check_freshness(current_year=2030, max_age=1)
        assert len(stale) > 0, "Expected stale constants for current_year=2030"
        for meta in stale:
            assert meta.source_year <= 2028  # 2030 - 1 - 1

    def test_max_age_respected(self) -> None:
        """max_age parameter widens the freshness window."""
        # With max_age=10, even 2016 constants would be fresh for 2026.
        stale_strict = check_freshness(current_year=2026, max_age=0)
        stale_lenient = check_freshness(current_year=2026, max_age=10)
        assert len(stale_lenient) <= len(stale_strict)

    def test_returns_list_of_constant_meta(self) -> None:
        stale = check_freshness(current_year=2100)
        assert isinstance(stale, list)
        for item in stale:
            assert isinstance(item, ConstantMeta)

    def test_empty_for_year_zero(self) -> None:
        """With max_age=1000, nothing is stale."""
        stale = check_freshness(current_year=2026, max_age=1000)
        assert stale == []


class TestCoverage:
    """Spot-check that key constants are present in the registry."""

    EXPECTED_CONSTANTS: ClassVar[set[str]] = {
        "ASK_RATE",
        "ASK_DEPOSIT_CAPS",
        "PAL_RATE",
        "AKTIEINDKOMST_LOW_RATE",
        "AKTIEINDKOMST_HIGH_RATE",
        "AKTIEINDKOMST_THRESHOLDS",
        "DK_TOPSKAT_RATE",
        "DK_TOPSKAT_THRESHOLD_DKK",
        "FOLKEPENSION_GRUNDBELOEB_MONTHLY_DKK",
        "FOLKEPENSION_TILLAEG_SINGLE_MONTHLY_DKK",
        "FOLKEPENSION_TILLAEG_MARRIED_MONTHLY_DKK",
        "FOLKEPENSION_MODREGNING_RATE",
        "FOLKEPENSION_INCOME_THRESHOLD_DKK",
        "FOLKEPENSION_AGE_SCHEDULE",
    }

    def test_all_expected_constants_registered(self) -> None:
        registered = {m.constant for m in ALL_PLANNING_CONSTANTS}
        missing = self.EXPECTED_CONSTANTS - registered
        assert not missing, f"Constants missing from registry: {missing}"

    @pytest.mark.parametrize("constant", sorted(EXPECTED_CONSTANTS))
    def test_constant_has_metadata(self, constant: str) -> None:
        meta = next(
            (m for m in ALL_PLANNING_CONSTANTS if m.constant == constant), None
        )
        assert meta is not None, f"{constant!r} not found in ALL_PLANNING_CONSTANTS"
        assert meta.source_year >= 2024
        assert meta.source_url.startswith("http")


class TestCheckFreshnessValidation:
    """check_freshness raises on invalid inputs."""

    def test_negative_max_age_raises(self) -> None:
        with pytest.raises(ValueError, match="max_age"):
            check_freshness(current_year=2026, max_age=-1)

    def test_zero_current_year_raises(self) -> None:
        with pytest.raises(ValueError, match="current_year"):
            check_freshness(current_year=0)

    def test_negative_current_year_raises(self) -> None:
        with pytest.raises(ValueError, match="current_year"):
            check_freshness(current_year=-1)

    def test_float_current_year_raises(self) -> None:
        with pytest.raises(TypeError, match="current_year"):
            check_freshness(current_year=2026.0)  # type: ignore[arg-type]

    def test_float_max_age_raises(self) -> None:
        with pytest.raises(TypeError, match="max_age"):
            check_freshness(current_year=2026, max_age=1.5)  # type: ignore[arg-type]

    def test_zero_max_age_allowed(self) -> None:
        # max_age=0 means the constant must be confirmed for *current_year*
        result = check_freshness(current_year=2026, max_age=0)
        assert isinstance(result, list)
