"""Tests for penge.sim.assumptions — investment assumption catalog.

Coverage:
* InstrumentAssumptions creation and field retrieval
* TaxRegime variants (LAGER, REALISATION, ASK)
* AssumptionCatalog add / get / get_or_none / all
* KeyError on missing ISIN
* Validation errors for negative or out-of-range fields
* validate() warnings (ask_eligible mismatch, DKK + fx_cost, high dividend)
* Override semantics (second add() wins)
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from penge.sim.assumptions import AssumptionCatalog, InstrumentAssumptions, TaxRegime

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MSCI_WORLD_ISIN = "IE00B4L5Y983"
STOXX_ISIN = "IE00B0M62Q58"
ASK_ISIN = "DK0060950053"
DKK_ISIN = "DK0016272602"


def _msci_world() -> InstrumentAssumptions:
    """Typical Lager-taxed EUR-denominated ETF."""
    return InstrumentAssumptions(
        isin=MSCI_WORLD_ISIN,
        label="iShares Core MSCI World UCITS ETF (Acc)",
        currency="EUR",
        tax_regime=TaxRegime.LAGER,
        expense_ratio=Decimal("0.002"),
        dividend_yield=Decimal("0"),
        ask_eligible=False,
        fx_cost=Decimal("0.0025"),
        notes="ABIS-listed; held in frie midler",
    )


def _realisation_fund() -> InstrumentAssumptions:
    """Distributing fund under realisation taxation."""
    return InstrumentAssumptions(
        isin=STOXX_ISIN,
        label="iShares MSCI Europe UCITS ETF (Dist)",
        currency="EUR",
        tax_regime=TaxRegime.REALISATION,
        expense_ratio=Decimal("0.0035"),
        dividend_yield=Decimal("0.025"),
        ask_eligible=False,
        fx_cost=Decimal("0.0025"),
    )


def _ask_fund() -> InstrumentAssumptions:
    """ASK-eligible accumulation fund."""
    return InstrumentAssumptions(
        isin=ASK_ISIN,
        label="Example ASK-eligible fund",
        currency="DKK",
        tax_regime=TaxRegime.ASK,
        expense_ratio=Decimal("0.005"),
        dividend_yield=Decimal("0"),
        ask_eligible=True,
        fx_cost=Decimal("0"),
    )


# ---------------------------------------------------------------------------
# 1. Create instrument with all fields; verify retrieval
# ---------------------------------------------------------------------------


def test_instrument_all_fields_round_trip() -> None:
    entry = _msci_world()

    assert entry.isin == MSCI_WORLD_ISIN
    assert entry.label == "iShares Core MSCI World UCITS ETF (Acc)"
    assert entry.currency == "EUR"
    assert entry.tax_regime == TaxRegime.LAGER
    assert entry.expense_ratio == Decimal("0.002")
    assert entry.dividend_yield == Decimal("0")
    assert entry.ask_eligible is False
    assert entry.fx_cost == Decimal("0.0025")
    assert entry.notes == "ABIS-listed; held in frie midler"


# ---------------------------------------------------------------------------
# 2. TaxRegime variants
# ---------------------------------------------------------------------------


def test_tax_regime_lager() -> None:
    entry = _msci_world()
    assert entry.tax_regime == TaxRegime.LAGER
    assert entry.tax_regime.value == "lager"


def test_tax_regime_realisation() -> None:
    entry = _realisation_fund()
    assert entry.tax_regime == TaxRegime.REALISATION
    assert entry.tax_regime.value == "realisation"


def test_tax_regime_ask() -> None:
    entry = _ask_fund()
    assert entry.tax_regime == TaxRegime.ASK
    assert entry.tax_regime.value == "ask"


# ---------------------------------------------------------------------------
# 3. AssumptionCatalog: add / get / all
# ---------------------------------------------------------------------------


def test_catalog_add_and_get() -> None:
    catalog = AssumptionCatalog()
    entry = _msci_world()
    catalog.add(entry)
    assert catalog.get(MSCI_WORLD_ISIN) is entry


def test_catalog_all_returns_all_entries() -> None:
    catalog = AssumptionCatalog()
    e1 = _msci_world()
    e2 = _realisation_fund()
    e3 = _ask_fund()
    catalog.add(e1)
    catalog.add(e2)
    catalog.add(e3)
    result = catalog.all()
    assert len(result) == 3
    assert e1 in result
    assert e2 in result
    assert e3 in result


# ---------------------------------------------------------------------------
# 4. get() on missing ISIN raises KeyError
# ---------------------------------------------------------------------------


def test_get_missing_isin_raises_key_error() -> None:
    catalog = AssumptionCatalog()
    with pytest.raises(KeyError):
        catalog.get("IE0000000000")


# ---------------------------------------------------------------------------
# 5. get_or_none() returns None for missing ISIN
# ---------------------------------------------------------------------------


def test_get_or_none_missing_returns_none() -> None:
    catalog = AssumptionCatalog()
    assert catalog.get_or_none("IE0000000000") is None


def test_get_or_none_present_returns_entry() -> None:
    catalog = AssumptionCatalog()
    entry = _msci_world()
    catalog.add(entry)
    assert catalog.get_or_none(MSCI_WORLD_ISIN) is entry


# ---------------------------------------------------------------------------
# 6. Negative expense_ratio raises ValueError
# ---------------------------------------------------------------------------


def test_negative_expense_ratio_raises() -> None:
    with pytest.raises(ValueError, match="expense_ratio cannot be negative"):
        InstrumentAssumptions(
            isin=MSCI_WORLD_ISIN,
            label="Test",
            currency="EUR",
            tax_regime=TaxRegime.LAGER,
            expense_ratio=Decimal("-0.001"),
        )


def test_zero_expense_ratio_is_valid() -> None:
    entry = InstrumentAssumptions(
        isin=MSCI_WORLD_ISIN,
        label="Zero-cost instrument",
        currency="EUR",
        tax_regime=TaxRegime.LAGER,
        expense_ratio=Decimal("0"),
    )
    assert entry.expense_ratio == Decimal("0")


# ---------------------------------------------------------------------------
# 7. dividend_yield > 1 raises ValueError
# ---------------------------------------------------------------------------


def test_dividend_yield_above_one_raises() -> None:
    with pytest.raises(ValueError, match="dividend_yield must be between 0 and 1"):
        InstrumentAssumptions(
            isin=STOXX_ISIN,
            label="Test",
            currency="EUR",
            tax_regime=TaxRegime.REALISATION,
            expense_ratio=Decimal("0.003"),
            dividend_yield=Decimal("1.5"),
        )


def test_dividend_yield_negative_raises() -> None:
    with pytest.raises(ValueError, match="dividend_yield must be between 0 and 1"):
        InstrumentAssumptions(
            isin=STOXX_ISIN,
            label="Test",
            currency="EUR",
            tax_regime=TaxRegime.REALISATION,
            expense_ratio=Decimal("0.003"),
            dividend_yield=Decimal("-0.01"),
        )


def test_dividend_yield_boundary_values_are_valid() -> None:
    for yield_val in (Decimal("0"), Decimal("1")):
        entry = InstrumentAssumptions(
            isin=STOXX_ISIN,
            label="Boundary test",
            currency="EUR",
            tax_regime=TaxRegime.REALISATION,
            expense_ratio=Decimal("0.003"),
            dividend_yield=yield_val,
        )
        assert entry.dividend_yield == yield_val


# ---------------------------------------------------------------------------
# 8. Negative fx_cost raises ValueError
# ---------------------------------------------------------------------------


def test_negative_fx_cost_raises() -> None:
    with pytest.raises(ValueError, match="fx_cost cannot be negative"):
        InstrumentAssumptions(
            isin=MSCI_WORLD_ISIN,
            label="Test",
            currency="EUR",
            tax_regime=TaxRegime.LAGER,
            expense_ratio=Decimal("0.002"),
            fx_cost=Decimal("-0.001"),
        )


# ---------------------------------------------------------------------------
# 9. validate() warns for ask_eligible=True but non-ASK tax regime
# ---------------------------------------------------------------------------


def test_validate_ask_eligible_but_not_ask_regime() -> None:
    catalog = AssumptionCatalog()
    catalog.add(
        InstrumentAssumptions(
            isin=ASK_ISIN,
            label="Mislabeled ASK instrument",
            currency="DKK",
            tax_regime=TaxRegime.LAGER,  # wrong: should be ASK
            expense_ratio=Decimal("0.005"),
            ask_eligible=True,
        )
    )
    warnings = catalog.validate()
    assert len(warnings) == 1
    assert ASK_ISIN in warnings[0]
    assert "ask_eligible=True" in warnings[0]
    assert "TaxRegime.ASK" in warnings[0]


# ---------------------------------------------------------------------------
# 10. validate() warns for DKK instrument with fx_cost > 0
# ---------------------------------------------------------------------------


def test_validate_dkk_instrument_with_fx_cost() -> None:
    catalog = AssumptionCatalog()
    catalog.add(
        InstrumentAssumptions(
            isin=DKK_ISIN,
            label="DKK fund with FX cost",
            currency="DKK",
            tax_regime=TaxRegime.LAGER,
            expense_ratio=Decimal("0.005"),
            fx_cost=Decimal("0.001"),  # unusual
        )
    )
    warnings = catalog.validate()
    assert any(DKK_ISIN in w and "DKK" in w for w in warnings)


# ---------------------------------------------------------------------------
# 11. validate() returns empty list for a clean catalog
# ---------------------------------------------------------------------------


def test_validate_clean_catalog_returns_no_warnings() -> None:
    catalog = AssumptionCatalog()
    catalog.add(_msci_world())
    catalog.add(_realisation_fund())
    catalog.add(_ask_fund())
    warnings = catalog.validate()
    assert warnings == []


# ---------------------------------------------------------------------------
# 12. Override: add same ISIN twice — second entry wins
# ---------------------------------------------------------------------------


def test_add_same_isin_second_wins() -> None:
    catalog = AssumptionCatalog()
    first = InstrumentAssumptions(
        isin=MSCI_WORLD_ISIN,
        label="First version",
        currency="EUR",
        tax_regime=TaxRegime.LAGER,
        expense_ratio=Decimal("0.002"),
        notes="original",
    )
    second = InstrumentAssumptions(
        isin=MSCI_WORLD_ISIN,
        label="Updated version",
        currency="EUR",
        tax_regime=TaxRegime.LAGER,
        expense_ratio=Decimal("0.0015"),  # corrected ÅOP
        notes="override: new TER from fund factsheet 2024-01",
    )
    catalog.add(first)
    catalog.add(second)

    result = catalog.get(MSCI_WORLD_ISIN)
    assert result is second
    assert result.expense_ratio == Decimal("0.0015")
    assert result.notes == "override: new TER from fund factsheet 2024-01"
    # only one entry in catalog
    assert len(catalog.all()) == 1


# ---------------------------------------------------------------------------
# Additional: high dividend_yield on Realisation triggers warning
# ---------------------------------------------------------------------------


def test_validate_high_dividend_yield_on_realisation() -> None:
    catalog = AssumptionCatalog()
    catalog.add(
        InstrumentAssumptions(
            isin=STOXX_ISIN,
            label="Unusually high yield fund",
            currency="EUR",
            tax_regime=TaxRegime.REALISATION,
            expense_ratio=Decimal("0.004"),
            dividend_yield=Decimal("0.15"),  # 15 % — suspicious
        )
    )
    warnings = catalog.validate()
    assert any(STOXX_ISIN in w and "dividend_yield" in w for w in warnings)


def test_validate_multiple_warnings_returned() -> None:
    """A single entry can trigger multiple independent warnings."""
    catalog = AssumptionCatalog()
    catalog.add(
        InstrumentAssumptions(
            isin=DKK_ISIN,
            label="Problematic DKK fund",
            currency="DKK",
            tax_regime=TaxRegime.LAGER,
            expense_ratio=Decimal("0.005"),
            ask_eligible=True,  # triggers warning 1: not ASK regime
            fx_cost=Decimal("0.002"),  # triggers warning 2: DKK + fx_cost
        )
    )
    warnings = catalog.validate()
    assert len(warnings) == 2


# ---------------------------------------------------------------------------
# Additional: InstrumentAssumptions is frozen (immutable)
# ---------------------------------------------------------------------------


def test_instrument_assumptions_is_frozen() -> None:
    entry = _msci_world()
    with pytest.raises((AttributeError, TypeError)):
        entry.expense_ratio = Decimal("0.999")  # type: ignore[misc]  # frozen=True raises FrozenInstanceError


# ---------------------------------------------------------------------------
# Additional: unsupported currency raises ValueError
# ---------------------------------------------------------------------------


def test_unsupported_currency_raises() -> None:
    with pytest.raises(ValueError, match="currency must be 'EUR' or 'DKK'"):
        InstrumentAssumptions(
            isin=MSCI_WORLD_ISIN,
            label="USD fund",
            currency="USD",  # type: ignore[arg-type]  # intentional invalid value for test
            tax_regime=TaxRegime.LAGER,
            expense_ratio=Decimal("0.002"),
        )  # frozen=True raises FrozenInstanceError
