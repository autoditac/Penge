"""Smoke tests for the GLS thin wrapper.

The shared upsert behavior is covered by
``tests/ingest/enablebanking/test_mapping.py``; here we just verify
that the per-bank wrapper passes the correct provider slug.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from penge.ingest.gls.loader import PROVIDER, load_account


def test_provider_slug_is_gls() -> None:
    assert PROVIDER == "gls"


def test_load_account_delegates_with_provider_gls() -> None:
    with patch("penge.ingest.gls.loader._load_account") as delegate:
        load_account(
            engine=MagicMock(),
            client=MagicMock(),
            account_uid="uid-1",
            entity_name="Account Holder",
            account_name="GLS Girokonto",
            currency="EUR",
            iban="DE12345678901234567890",
            date_from=date(2025, 1, 1),
            date_to=date(2025, 12, 31),
        )
    kwargs = delegate.call_args.kwargs
    assert kwargs["provider"] == "gls"
    assert kwargs["account_uid"] == "uid-1"
