"""Evangelische Bank → Postgres loader (thin wrapper).

The actual upsert logic lives in
:mod:`penge.ingest.enablebanking.loader`. This module fixes the
provider slug to ``"ebank"`` so callers don't have to.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from penge.ingest.enablebanking.loader import LoadResult
from penge.ingest.enablebanking.loader import load_account as _load_account

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

    from penge.ingest.enablebanking.client import Client

PROVIDER = "ebank"


def load_account(
    engine: Engine,
    *,
    client: Client,
    account_uid: str,
    entity_name: str,
    account_name: str,
    currency: str = "EUR",
    iban: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> LoadResult:
    """Pull transactions + balance for one Evangelische Bank account and persist."""
    return _load_account(
        engine,
        provider=PROVIDER,
        client=client,
        account_uid=account_uid,
        entity_name=entity_name,
        account_name=account_name,
        currency=currency,
        iban=iban,
        date_from=date_from,
        date_to=date_to,
    )


__all__ = ["PROVIDER", "LoadResult", "load_account"]
