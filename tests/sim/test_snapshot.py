"""Tests for penge.sim.snapshot — HouseholdSnapshot and SnapshotBuilder.

All fixtures are synthetic; no real personal data is used.
"""

from __future__ import annotations

from decimal import Decimal

from penge.sim.snapshot import (
    SnapshotBuilder,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DATE = "2025-01-15"


def _builder() -> SnapshotBuilder:
    return SnapshotBuilder(_DATE)


# ---------------------------------------------------------------------------
# 1. Single cash account
# ---------------------------------------------------------------------------


def test_single_cash_account_balance_and_kind() -> None:
    snapshot = (
        _builder()
        .add_account(
            account_id="acc-001",
            entity_name="lars",
            account_name="GLS lønkonto",
            kind="cash",
            currency="DKK",
            balance=Decimal("45000"),
            provider="gls",
            data_source="EnableBanking 2025-01-15",
        )
        .build()
    )

    assert snapshot.snapshot_date == _DATE
    assert len(snapshot.accounts) == 1
    acc = snapshot.accounts[0]
    assert acc.kind == "cash"
    assert acc.balance == Decimal("45000")
    assert acc.currency == "DKK"
    assert acc.entity_name == "lars"
    assert not snapshot.missing_assumptions


# ---------------------------------------------------------------------------
# 2. All four non-cash kinds — total_by_kind per kind
# ---------------------------------------------------------------------------


def test_multiple_kinds_total_by_kind() -> None:
    snapshot = (
        _builder()
        .add_account(
            account_id="ask-001",
            entity_name="lars",
            account_name="Nordnet ASK",
            kind="ask",
            currency="DKK",
            balance=Decimal("102000"),
            provider="nordnet",
            data_source="CSV import 2025-01",
        )
        .add_account(
            account_id="fm-001",
            entity_name="lars",
            account_name="Nordnet frie midler",
            kind="frie_midler",
            currency="DKK",
            balance=Decimal("250000"),
            provider="nordnet",
            data_source="CSV import 2025-01",
        )
        .add_account(
            account_id="pen-001",
            entity_name="lars",
            account_name="PFA pension",
            kind="pension",
            currency="DKK",
            balance=Decimal("800000"),
            provider="pfa",
            data_source="PDF import 2025-03",
        )
        .add_account(
            account_id="man-001",
            entity_name="lars",
            account_name="Growney",
            kind="manual",
            currency="EUR",
            balance=Decimal("12000"),
            provider="manual",
            data_source="manual 2025-01",
        )
        .build()
    )

    assert snapshot.total_by_kind("ask") == {"EUR": Decimal("0"), "DKK": Decimal("102000")}
    assert snapshot.total_by_kind("frie_midler") == {
        "EUR": Decimal("0"),
        "DKK": Decimal("250000"),
    }
    assert snapshot.total_by_kind("pension") == {"EUR": Decimal("0"), "DKK": Decimal("800000")}
    assert snapshot.total_by_kind("manual") == {"EUR": Decimal("12000"), "DKK": Decimal("0")}


# ---------------------------------------------------------------------------
# 3. EUR and DKK don't cross-contaminate in total_by_kind
# ---------------------------------------------------------------------------


def test_eur_dkk_no_cross_contamination() -> None:
    snapshot = (
        _builder()
        .add_account(
            account_id="ask-eur",
            entity_name="lars",
            account_name="Nordnet ASK EUR",
            kind="ask",
            currency="EUR",
            balance=Decimal("5000"),
            provider="nordnet",
            data_source="CSV 2025-01",
        )
        .add_account(
            account_id="ask-dkk",
            entity_name="lars",
            account_name="Nordnet ASK DKK",
            kind="ask",
            currency="DKK",
            balance=Decimal("50000"),
            provider="nordnet",
            data_source="CSV 2025-01",
        )
        .build()
    )

    totals = snapshot.total_by_kind("ask")
    assert totals["EUR"] == Decimal("5000")
    assert totals["DKK"] == Decimal("50000")

    # A different kind returns all zeros
    cash_totals = snapshot.total_by_kind("cash")
    assert cash_totals["EUR"] == Decimal("0")
    assert cash_totals["DKK"] == Decimal("0")


# ---------------------------------------------------------------------------
# 4. Unknown kind triggers missing_assumption and falls back to "manual"
# ---------------------------------------------------------------------------


def test_unknown_kind_triggers_missing_assumption() -> None:
    snapshot = (
        _builder()
        .add_account(
            account_id="acc-x",
            entity_name="lars",
            account_name="Mystery account",
            kind="savings",  # not a valid kind
            currency="DKK",
            balance=Decimal("1000"),
            provider="unknown",
            data_source="manual",
        )
        .build()
    )

    assert len(snapshot.missing_assumptions) == 1
    assert "savings" in snapshot.missing_assumptions[0]
    assert "acc-x" in snapshot.missing_assumptions[0]
    # Kind should fall back to "manual"
    assert snapshot.accounts[0].kind == "manual"


# ---------------------------------------------------------------------------
# 5. Unsupported currency triggers missing_assumption
# ---------------------------------------------------------------------------


def test_unsupported_currency_triggers_missing_assumption() -> None:
    snapshot = (
        _builder()
        .add_account(
            account_id="acc-usd",
            entity_name="sofie",
            account_name="US brokerage",
            kind="frie_midler",
            currency="USD",  # not supported
            balance=Decimal("3000"),
            provider="manual",
            data_source="manual 2025-01",
        )
        .build()
    )

    assert len(snapshot.missing_assumptions) == 1
    assert "USD" in snapshot.missing_assumptions[0]
    assert "acc-usd" in snapshot.missing_assumptions[0]


# ---------------------------------------------------------------------------
# 6. Holding with cost_basis=None triggers missing_assumption
# ---------------------------------------------------------------------------


def test_holding_no_cost_basis_triggers_missing_assumption() -> None:
    snapshot = (
        _builder()
        .add_holding(
            account_id="fm-001",
            isin="IE00B4L5Y983",
            instrument_name="iShares Core MSCI World",
            quantity=Decimal("42.5"),
            market_value=Decimal("125000"),
            cost_basis=None,
            currency="DKK",
            data_source="CSV 2025-01",
        )
        .build()
    )

    assert len(snapshot.missing_assumptions) == 1
    assert "IE00B4L5Y983" in snapshot.missing_assumptions[0]
    assert "cost_basis" in snapshot.missing_assumptions[0]


# ---------------------------------------------------------------------------
# 7. holdings_by_account returns correct subset
# ---------------------------------------------------------------------------


def test_holdings_by_account_returns_subset() -> None:
    snapshot = (
        _builder()
        .add_holding(
            account_id="acc-A",
            isin="IE00B4L5Y983",
            instrument_name="iShares MSCI World",
            quantity=Decimal("10"),
            market_value=Decimal("30000"),
            cost_basis=Decimal("25000"),
            currency="DKK",
            data_source="CSV 2025-01",
        )
        .add_holding(
            account_id="acc-B",
            isin="LU1681048804",
            instrument_name="Xtrackers MSCI World Swap",
            quantity=Decimal("5"),
            market_value=Decimal("15000"),
            cost_basis=Decimal("12000"),
            currency="DKK",
            data_source="CSV 2025-01",
        )
        .add_holding(
            account_id="acc-A",
            isin="IE00B0M62Q58",
            instrument_name="iShares MSCI EM",
            quantity=Decimal("20"),
            market_value=Decimal("18000"),
            cost_basis=Decimal("16000"),
            currency="DKK",
            data_source="CSV 2025-01",
        )
        .build()
    )

    holdings_a = snapshot.holdings_by_account("acc-A")
    assert len(holdings_a) == 2
    isins_a = {h.isin for h in holdings_a}
    assert isins_a == {"IE00B4L5Y983", "IE00B0M62Q58"}

    holdings_b = snapshot.holdings_by_account("acc-B")
    assert len(holdings_b) == 1
    assert holdings_b[0].isin == "LU1681048804"

    # Non-existent account returns empty list
    assert snapshot.holdings_by_account("acc-none") == []


# ---------------------------------------------------------------------------
# 8. accounts_by_entity returns correct subset
# ---------------------------------------------------------------------------


def test_accounts_by_entity_returns_subset() -> None:
    snapshot = (
        _builder()
        .add_account(
            account_id="lars-1",
            entity_name="lars",
            account_name="GLS lønkonto",
            kind="cash",
            currency="DKK",
            balance=Decimal("40000"),
            provider="gls",
            data_source="EB 2025-01",
        )
        .add_account(
            account_id="sofie-1",
            entity_name="sofie",
            account_name="Lunar konto",
            kind="cash",
            currency="DKK",
            balance=Decimal("22000"),
            provider="lunar",
            data_source="EB 2025-01",
        )
        .add_account(
            account_id="lars-2",
            entity_name="lars",
            account_name="Nordnet ASK",
            kind="ask",
            currency="DKK",
            balance=Decimal("98000"),
            provider="nordnet",
            data_source="CSV 2025-01",
        )
        .build()
    )

    lars_accounts = snapshot.accounts_by_entity("lars")
    assert len(lars_accounts) == 2
    assert {a.account_id for a in lars_accounts} == {"lars-1", "lars-2"}

    sofie_accounts = snapshot.accounts_by_entity("sofie")
    assert len(sofie_accounts) == 1
    assert sofie_accounts[0].account_id == "sofie-1"

    # Non-existent entity returns empty list
    assert snapshot.accounts_by_entity("unknown") == []


# ---------------------------------------------------------------------------
# 9. Multi-entity snapshot filters correctly
# ---------------------------------------------------------------------------


def test_multi_entity_snapshot_filters_correctly() -> None:
    snapshot = (
        _builder()
        .add_account(
            account_id="l-cash",
            entity_name="lars",
            account_name="GLS",
            kind="cash",
            currency="DKK",
            balance=Decimal("10000"),
            provider="gls",
            data_source="EB 2025-01",
        )
        .add_account(
            account_id="l-ask",
            entity_name="lars",
            account_name="ASK",
            kind="ask",
            currency="DKK",
            balance=Decimal("50000"),
            provider="nordnet",
            data_source="CSV 2025-01",
        )
        .add_account(
            account_id="s-cash",
            entity_name="sofie",
            account_name="Lunar",
            kind="cash",
            currency="DKK",
            balance=Decimal("8000"),
            provider="lunar",
            data_source="EB 2025-01",
        )
        .add_account(
            account_id="s-fm",
            entity_name="sofie",
            account_name="Frie midler",
            kind="frie_midler",
            currency="EUR",
            balance=Decimal("6000"),
            provider="nordnet",
            data_source="CSV 2025-01",
        )
        .build()
    )

    lars = snapshot.accounts_by_entity("lars")
    sofie = snapshot.accounts_by_entity("sofie")

    assert {a.account_id for a in lars} == {"l-cash", "l-ask"}
    assert {a.account_id for a in sofie} == {"s-cash", "s-fm"}
    # No overlap
    lars_ids = {a.account_id for a in lars}
    sofie_ids = {a.account_id for a in sofie}
    assert lars_ids.isdisjoint(sofie_ids)


# ---------------------------------------------------------------------------
# 10. Happy-path FIRE scenario: lars (cash + ASK + pension) + sofie (cash + frie_midler)
# ---------------------------------------------------------------------------


def test_happy_path_fire_scenario() -> None:
    """Complete FIRE scenario with no missing assumptions."""
    snapshot = (
        SnapshotBuilder("2025-01-15")
        # Lars
        .add_account(
            account_id="lars-gls",
            entity_name="lars",
            account_name="GLS lønkonto",
            kind="cash",
            currency="DKK",
            balance=Decimal("45000"),
            provider="gls",
            data_source="EnableBanking 2025-01-15",
        )
        .add_account(
            account_id="lars-ask",
            entity_name="lars",
            account_name="Nordnet ASK",
            kind="ask",
            currency="DKK",
            balance=Decimal("102000"),
            provider="nordnet",
            data_source="CSV import 2025-01",
        )
        .add_account(
            account_id="lars-pfa",
            entity_name="lars",
            account_name="PFA pension",
            kind="pension",
            currency="DKK",
            balance=Decimal("820000"),
            provider="pfa",
            data_source="PDF import 2025-03",
        )
        # Sofie
        .add_account(
            account_id="sofie-lunar",
            entity_name="sofie",
            account_name="Lunar konto",
            kind="cash",
            currency="DKK",
            balance=Decimal("22000"),
            provider="lunar",
            data_source="EnableBanking 2025-01-15",
        )
        .add_account(
            account_id="sofie-fm",
            entity_name="sofie",
            account_name="Nordnet frie midler",
            kind="frie_midler",
            currency="DKK",
            balance=Decimal("315000"),
            provider="nordnet",
            data_source="CSV import 2025-01",
        )
        # Holdings for lars ASK
        .add_holding(
            account_id="lars-ask",
            isin="IE00B4L5Y983",
            instrument_name="iShares Core MSCI World (Acc)",
            quantity=Decimal("34.2"),
            market_value=Decimal("102000"),
            cost_basis=Decimal("88000"),
            currency="DKK",
            data_source="CSV import 2025-01",
        )
        # Holdings for sofie frie midler
        .add_holding(
            account_id="sofie-fm",
            isin="LU1681048804",
            instrument_name="Xtrackers MSCI World Swap",
            quantity=Decimal("100"),
            market_value=Decimal("315000"),
            cost_basis=Decimal("270000"),
            currency="DKK",
            data_source="CSV import 2025-01",
        )
        .build()
    )

    # No missing assumptions — everything is clean
    assert snapshot.missing_assumptions == [], snapshot.missing_assumptions

    # Balances per entity
    lars_accounts = snapshot.accounts_by_entity("lars")
    sofie_accounts = snapshot.accounts_by_entity("sofie")
    assert len(lars_accounts) == 3
    assert len(sofie_accounts) == 2

    # Total balances by kind
    assert snapshot.total_by_kind("cash")["DKK"] == Decimal("67000")  # 45000 + 22000
    assert snapshot.total_by_kind("ask")["DKK"] == Decimal("102000")
    assert snapshot.total_by_kind("pension")["DKK"] == Decimal("820000")
    assert snapshot.total_by_kind("frie_midler")["DKK"] == Decimal("315000")

    # Holdings attached correctly
    ask_holdings = snapshot.holdings_by_account("lars-ask")
    assert len(ask_holdings) == 1
    assert ask_holdings[0].isin == "IE00B4L5Y983"
    assert ask_holdings[0].cost_basis == Decimal("88000")

    fm_holdings = snapshot.holdings_by_account("sofie-fm")
    assert len(fm_holdings) == 1
    assert fm_holdings[0].isin == "LU1681048804"

    # Snapshot metadata
    assert snapshot.snapshot_date == "2025-01-15"


# ---------------------------------------------------------------------------
# Extra: balance accepts string input (Decimal conversion)
# ---------------------------------------------------------------------------


def test_balance_accepts_string_input() -> None:
    snapshot = (
        _builder()
        .add_account(
            account_id="acc-str",
            entity_name="lars",
            account_name="Test",
            kind="cash",
            currency="DKK",
            balance="12345.67",  # string
            provider="manual",
            data_source="manual",
        )
        .build()
    )
    assert snapshot.accounts[0].balance == Decimal("12345.67")


# ---------------------------------------------------------------------------
# Extra: both kind AND currency errors accumulate in one pass
# ---------------------------------------------------------------------------


def test_both_kind_and_currency_errors_accumulate() -> None:
    snapshot = (
        _builder()
        .add_account(
            account_id="acc-bad",
            entity_name="lars",
            account_name="Bad account",
            kind="unknown_kind",
            currency="GBP",
            balance=Decimal("500"),
            provider="manual",
            data_source="manual",
        )
        .build()
    )

    assert len(snapshot.missing_assumptions) == 2
    messages = " ".join(snapshot.missing_assumptions)
    assert "unknown_kind" in messages
    assert "GBP" in messages
