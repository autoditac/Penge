"""Lunar → Postgres loader (thin wrapper).

The actual upsert logic lives in
:mod:`penge.ingest.enablebanking.loader`. This module fixes the
provider slug to ``"lunar"`` and detects Aktiesparekonto subaccounts
so they carry the right ``dk_tax_treatment`` tag.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from penge.ingest.enablebanking.loader import LoadResult
from penge.ingest.enablebanking.loader import load_account as _load_account

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

    from penge.ingest.enablebanking.client import Client

PROVIDER = "lunar"
DK_TAX_AKTIESPAREKONTO = "aktiesparekonto"


def is_aktiesparekonto(*, product: str | None, name: str | None) -> bool:
    """Return ``True`` if this Lunar subaccount is an Aktiesparekonto.

    Lunar tags ASK subaccounts via the Berlin Group ``product`` field
    (``"Aktiesparekonto"``). As a defensive fallback we also accept a
    case-insensitive substring match in the ``name`` so manually
    renamed accounts are still detected. Both inputs are optional.
    """
    needle = "aktiesparekonto"
    return any(raw is not None and needle in raw.lower() for raw in (product, name))


def load_account(
    engine: Engine,
    *,
    client: Client,
    account_uid: str,
    entity_name: str,
    account_name: str,
    currency: str = "DKK",
    iban: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    product: str | None = None,
    dk_tax_treatment: str | None = None,
) -> LoadResult:
    """Pull transactions + balance for one Lunar account and persist.

    If ``dk_tax_treatment`` is not given explicitly, it is inferred
    from ``product`` / ``account_name`` via :func:`is_aktiesparekonto`.
    Pass ``dk_tax_treatment=""`` to force ``None`` and bypass detection
    (e.g. in tests).
    """
    if dk_tax_treatment is None and is_aktiesparekonto(product=product, name=account_name):
        dk_tax_treatment = DK_TAX_AKTIESPAREKONTO
    elif dk_tax_treatment == "":
        dk_tax_treatment = None

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
        dk_tax_treatment=dk_tax_treatment,
    )


__all__ = [
    "DK_TAX_AKTIESPAREKONTO",
    "PROVIDER",
    "LoadResult",
    "is_aktiesparekonto",
    "load_account",
]
