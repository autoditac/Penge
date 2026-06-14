"""Unit tests for the provider registry (no DB)."""

from __future__ import annotations

from penge.api.connections.provider import all_providers, get_provider


def test_known_providers() -> None:
    slugs = {p.slug for p in all_providers()}
    assert slugs == {"gls", "ebank", "lunar"}


def test_gls_aspsp_name_matches_production_catalogue() -> None:
    gls = get_provider("gls")
    assert gls is not None
    assert gls.aspsp_name == "GLS Gemeinschaftsbank"
    assert gls.aspsp_country == "DE"


def test_lunar_is_danish_dkk() -> None:
    lunar = get_provider("lunar")
    assert lunar is not None
    assert lunar.aspsp_country == "DK"
    assert lunar.default_currency == "DKK"


def test_unknown_provider_returns_none() -> None:
    assert get_provider("nope") is None
