"""Unit tests for the manual-entry CLI.

These cover input validation on :class:`BalanceEntry` /
:class:`PropertyEntry` and the Typer command surface (using
``CliRunner``). Database persistence is covered by integration tests
gated on ``PENGE_TEST_DATABASE_URL`` like the other ingest connectors.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from typer.testing import CliRunner

from penge.manual import BalanceEntry, PropertyEntry
from penge.manual.__main__ import app

runner = CliRunner()


# --------------------------------------------------------------------------- #
# Entry validation
# --------------------------------------------------------------------------- #


def test_balance_entry_normalises_currency() -> None:
    e = BalanceEntry(
        entity="Rouven",
        account_name="DKB Tagesgeld",
        currency="eur",
        as_of=date(2026, 5, 8),
        balance=Decimal("100"),
    )
    assert e.currency == "EUR"


def test_balance_entry_strips_whitespace_on_names() -> None:
    e = BalanceEntry(
        entity="  Rouven  ",
        account_name="\tDKB\n",
        currency="EUR",
        as_of=date(2026, 5, 8),
        balance=Decimal("0"),
    )
    assert e.entity == "Rouven"
    assert e.account_name == "DKB"


def test_balance_entry_rejects_empty_entity() -> None:
    with pytest.raises(ValueError, match="entity must not be empty"):
        BalanceEntry(
            entity="   ",
            account_name="X",
            currency="EUR",
            as_of=date(2026, 5, 8),
            balance=Decimal("0"),
        )


def test_balance_entry_rejects_negative_balance() -> None:
    with pytest.raises(ValueError, match="balance must be >= 0"):
        BalanceEntry(
            entity="Rouven",
            account_name="DKB",
            currency="EUR",
            as_of=date(2026, 5, 8),
            balance=Decimal("-1"),
        )


def test_balance_entry_rejects_non_iso_currency() -> None:
    with pytest.raises(ValueError, match="3-letter ISO code"):
        BalanceEntry(
            entity="Rouven",
            account_name="DKB",
            currency="EU",
            as_of=date(2026, 5, 8),
            balance=Decimal("0"),
        )
    with pytest.raises(ValueError, match="3-letter ISO code"):
        BalanceEntry(
            entity="Rouven",
            account_name="DKB",
            currency="EU1",
            as_of=date(2026, 5, 8),
            balance=Decimal("0"),
        )


def test_property_entry_validates_required_fields() -> None:
    with pytest.raises(ValueError, match="property_name must not be empty"):
        PropertyEntry(
            entity="Rouven",
            account_name="Nederbyvej 36",
            property_name="",
            currency="DKK",
            as_of=date(2026, 5, 8),
            valuation=Decimal("4500000"),
        )


def test_property_entry_rejects_negative_valuation() -> None:
    with pytest.raises(ValueError, match="valuation must be >= 0"):
        PropertyEntry(
            entity="Rouven",
            account_name="Nederbyvej 36",
            property_name="Nederbyvej 36 (DK)",
            currency="DKK",
            as_of=date(2026, 5, 8),
            valuation=Decimal("-100"),
        )


def test_balance_entry_is_immutable() -> None:
    import dataclasses

    e = BalanceEntry(
        entity="Rouven",
        account_name="DKB",
        currency="EUR",
        as_of=date(2026, 5, 8),
        balance=Decimal("100"),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        # Intentional mutation of a frozen dataclass to assert immutability.
        e.balance = Decimal("0")  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# CLI surface (no DB)
# --------------------------------------------------------------------------- #


def test_cli_help_lists_subcommands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "add-balance" in result.stdout
    assert "mark-property" in result.stdout


def test_cli_add_balance_rejects_invalid_decimal() -> None:
    # Should fail before touching the DB.
    result = runner.invoke(
        app,
        [
            "add-balance",
            "--entity",
            "Rouven",
            "--account",
            "DKB",
            "--currency",
            "EUR",
            "--balance",
            "not-a-number",
        ],
    )
    assert result.exit_code != 0
    assert "balance is not a valid decimal" in (result.stdout + (result.stderr or ""))


def test_cli_mark_property_rejects_bad_currency() -> None:
    result = runner.invoke(
        app,
        [
            "mark-property",
            "--entity",
            "Rouven",
            "--account",
            "Nederbyvej 36",
            "--property",
            "Nederbyvej 36 (DK)",
            "--currency",
            "DKKK",
            "--valuation",
            "100",
        ],
    )
    assert result.exit_code != 0
    output = result.stdout + (result.stderr or "")
    assert "3-letter ISO code" in output
