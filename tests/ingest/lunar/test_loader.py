"""Smoke tests for the Lunar thin wrapper.

The shared upsert behavior is covered by the Enable Banking mapping
tests (``tests/ingest/enablebanking/test_mapping.py``) and integration
tests; here we just verify that the per-bank wrapper:

* fixes ``provider="lunar"`` on the shared loader,
* auto-tags Aktiesparekonto subaccounts with the correct
  ``dk_tax_treatment``, and
* exposes the right ASPSP constants on the CLI.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from penge.ingest.lunar.loader import (
    DK_TAX_AKTIESPAREKONTO,
    PROVIDER,
    is_aktiesparekonto,
    load_account,
)


def test_provider_slug_is_lunar() -> None:
    assert PROVIDER == "lunar"


@pytest.mark.parametrize(  # type: ignore[untyped-decorator]  # pytest decorator is untyped under strict mypy
    ("product", "name", "expected"),
    [
        ("Aktiesparekonto", "ASK", True),
        ("CURRENT", "Lunar Aktiesparekonto Hovedkonto", True),
        ("aktiesparekonto", None, True),  # case-insensitive
        ("Current account", "Daglig konto", False),
        ("Current account", "ASK Lunar", False),  # bare "ASK" alone is ambiguous
        (None, None, False),
        (None, "Some random account", False),
    ],
)
def test_is_aktiesparekonto(product: str | None, name: str | None, expected: bool) -> None:
    assert is_aktiesparekonto(product=product, name=name) is expected


def test_load_account_delegates_with_provider_lunar() -> None:
    """``load_account`` must pass ``provider="lunar"`` and DKK default."""
    with patch("penge.ingest.lunar.loader._load_account") as delegate:
        load_account(
            engine=MagicMock(),
            client=MagicMock(),
            account_uid="uid-1",
            entity_name="Account Holder",
            account_name="Daglig konto",
            iban="DK1234567890123456",
            date_from=date(2025, 1, 1),
            date_to=date(2025, 12, 31),
        )
    assert delegate.call_count == 1
    kwargs = delegate.call_args.kwargs
    assert kwargs["provider"] == "lunar"
    assert kwargs["account_uid"] == "uid-1"
    assert kwargs["currency"] == "DKK"  # Lunar default
    assert kwargs["iban"] == "DK1234567890123456"
    assert kwargs["dk_tax_treatment"] is None


def test_load_account_auto_tags_aktiesparekonto_from_product() -> None:
    """When ``product='Aktiesparekonto'`` the wrapper auto-tags the account."""
    with patch("penge.ingest.lunar.loader._load_account") as delegate:
        load_account(
            engine=MagicMock(),
            client=MagicMock(),
            account_uid="uid-ask",
            entity_name="Account Holder",
            account_name="Lunar ASK",
            product="Aktiesparekonto",
        )
    assert delegate.call_args.kwargs["dk_tax_treatment"] == DK_TAX_AKTIESPAREKONTO


def test_load_account_auto_tags_aktiesparekonto_from_name_fallback() -> None:
    """When the name (not product) reveals ASK, the wrapper still tags."""
    with patch("penge.ingest.lunar.loader._load_account") as delegate:
        load_account(
            engine=MagicMock(),
            client=MagicMock(),
            account_uid="uid-ask",
            entity_name="Account Holder",
            account_name="Lunar Aktiesparekonto Hovedkonto",
            product="CURRENT",
        )
    assert delegate.call_args.kwargs["dk_tax_treatment"] == DK_TAX_AKTIESPAREKONTO


def test_load_account_explicit_dk_tax_treatment_wins() -> None:
    """Explicit ``dk_tax_treatment`` overrides auto-detection."""
    with patch("penge.ingest.lunar.loader._load_account") as delegate:
        load_account(
            engine=MagicMock(),
            client=MagicMock(),
            account_uid="uid",
            entity_name="Account Holder",
            account_name="Lunar Aktiesparekonto",
            product="Aktiesparekonto",
            autodetect_dk_tax_treatment=False,  # bypass detection
        )
    assert delegate.call_args.kwargs["dk_tax_treatment"] is None


def test_cli_aspsp_constants() -> None:
    """CLI module hardcodes the correct ASPSP name + country for Enable Banking."""
    from penge.ingest.lunar import __main__ as cli

    assert cli.ASPSP_NAME == "Lunar"
    assert cli.ASPSP_COUNTRY == "DK"
