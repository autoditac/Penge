"""Smoke tests for the EBank thin wrapper.

The shared upsert behavior is covered by the Enable Banking mapping
tests (`tests/ingest/enablebanking/test_mapping.py`) and integration
tests; here we just verify that the per-bank wrapper passes the
correct provider slug and forwards arguments unchanged.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from penge.ingest.ebank.loader import PROVIDER, load_account


def test_provider_slug_is_ebank() -> None:
    assert PROVIDER == "ebank"


def test_load_account_delegates_with_provider_ebank() -> None:
    """``load_account`` must pass ``provider="ebank"`` to the shared loader."""
    with patch("penge.ingest.ebank.loader._load_account") as delegate:
        load_account(
            engine=MagicMock(),
            client=MagicMock(),
            account_uid="uid-1",
            entity_name="Account Holder",
            account_name="Girokonto",
            currency="EUR",
            iban="DE12345678901234567890",
            date_from=date(2025, 1, 1),
            date_to=date(2025, 12, 31),
        )
    assert delegate.call_count == 1
    kwargs = delegate.call_args.kwargs
    assert kwargs["provider"] == "ebank"
    assert kwargs["account_uid"] == "uid-1"
    assert kwargs["entity_name"] == "Account Holder"
    assert kwargs["account_name"] == "Girokonto"
    assert kwargs["currency"] == "EUR"
    assert kwargs["iban"] == "DE12345678901234567890"
    assert kwargs["date_from"] == date(2025, 1, 1)
    assert kwargs["date_to"] == date(2025, 12, 31)


def test_cli_aspsp_constants() -> None:
    """CLI module hardcodes the correct ASPSP name + country for Enable Banking."""
    from penge.ingest.ebank import __main__ as cli

    assert cli.ASPSP_NAME == "Evangelische Bank"
    assert cli.ASPSP_COUNTRY == "DE"
