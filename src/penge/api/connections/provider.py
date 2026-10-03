"""Registry of the Enable Banking ASPSPs Penge can connect to.

Each provider binds a Penge slug to its Enable Banking ASPSP
identity and to the connector's ``load_account`` wrapper, so the
service layer can link / sync any of them through one code path while
preserving per-bank behaviour (e.g. Lunar's Aktiesparekonto
auto-detection).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from penge.ingest.ebank import loader as ebank_loader
from penge.ingest.gls import loader as gls_loader
from penge.ingest.lunar import loader as lunar_loader
from penge.ingest.paypal import loader as paypal_loader

if TYPE_CHECKING:
    from datetime import date

    from sqlalchemy.engine import Engine

    from penge.ingest.enablebanking.client import Client
    from penge.ingest.enablebanking.loader import LoadResult
    from penge.ingest.enablebanking.models import AccountResource


class _SyncAccount(Protocol):
    def __call__(
        self,
        engine: Engine,
        *,
        client: Client,
        account: AccountResource,
        connection_id: uuid.UUID,
        entity_name: str,
        date_from: date,
        date_to: date,
    ) -> LoadResult: ...


@dataclass(frozen=True, slots=True)
class Provider:
    """Static metadata + sync adapter for one Enable Banking ASPSP."""

    slug: str
    aspsp_name: str
    aspsp_country: str
    default_currency: str
    account_fallback: str
    psu_type: Literal["personal", "business"]
    data_role: Literal["cash_account", "payment_detail"]
    request_balances: bool
    request_transactions: bool
    sync_account: _SyncAccount | None


def _gls_sync(
    engine: Engine,
    *,
    client: Client,
    account: AccountResource,
    connection_id: uuid.UUID,
    entity_name: str,
    date_from: date,
    date_to: date,
) -> LoadResult:
    _ = connection_id
    if account.uid is None:  # pragma: no cover - filtered upstream
        raise ValueError("account has no uid")
    return gls_loader.load_account(
        engine,
        client=client,
        account_uid=account.uid,
        entity_name=entity_name,
        account_name=account.name or account.product or "GLS account",
        currency=(account.currency or "EUR").upper(),
        iban=account.account_id.iban if account.account_id else None,
        date_from=date_from,
        date_to=date_to,
    )


def _ebank_sync(
    engine: Engine,
    *,
    client: Client,
    account: AccountResource,
    connection_id: uuid.UUID,
    entity_name: str,
    date_from: date,
    date_to: date,
) -> LoadResult:
    _ = connection_id
    if account.uid is None:  # pragma: no cover - filtered upstream
        raise ValueError("account has no uid")
    return ebank_loader.load_account(
        engine,
        client=client,
        account_uid=account.uid,
        entity_name=entity_name,
        account_name=account.name or account.product or "Evangelische Bank account",
        currency=(account.currency or "EUR").upper(),
        iban=account.account_id.iban if account.account_id else None,
        date_from=date_from,
        date_to=date_to,
    )


def _lunar_sync(
    engine: Engine,
    *,
    client: Client,
    account: AccountResource,
    connection_id: uuid.UUID,
    entity_name: str,
    date_from: date,
    date_to: date,
) -> LoadResult:
    _ = connection_id
    if account.uid is None:  # pragma: no cover - filtered upstream
        raise ValueError("account has no uid")
    return lunar_loader.load_account(
        engine,
        client=client,
        account_uid=account.uid,
        entity_name=entity_name,
        account_name=account.name or account.product or "Lunar account",
        currency=(account.currency or "DKK").upper(),
        iban=account.account_id.iban if account.account_id else None,
        date_from=date_from,
        date_to=date_to,
        product=account.product,
    )


def _paypal_sync(
    engine: Engine,
    *,
    client: Client,
    account: AccountResource,
    connection_id: uuid.UUID,
    entity_name: str,
    date_from: date,
    date_to: date,
) -> LoadResult:
    _ = entity_name
    return paypal_loader.load_account(
        engine,
        client=client,
        account=account,
        connection_id=connection_id,
        date_from=date_from,
        date_to=date_to,
    )


_PROVIDERS: dict[str, Provider] = {
    "gls": Provider(
        slug="gls",
        aspsp_name="GLS Gemeinschaftsbank",
        aspsp_country="DE",
        default_currency="EUR",
        account_fallback="GLS account",
        psu_type="personal",
        data_role="cash_account",
        request_balances=True,
        request_transactions=True,
        sync_account=_gls_sync,
    ),
    "ebank": Provider(
        slug="ebank",
        aspsp_name="Evangelische Bank",
        aspsp_country="DE",
        default_currency="EUR",
        account_fallback="Evangelische Bank account",
        psu_type="personal",
        data_role="cash_account",
        request_balances=True,
        request_transactions=True,
        sync_account=_ebank_sync,
    ),
    "lunar": Provider(
        slug="lunar",
        aspsp_name="Lunar",
        aspsp_country="DK",
        default_currency="DKK",
        account_fallback="Lunar account",
        psu_type="personal",
        data_role="cash_account",
        request_balances=True,
        request_transactions=True,
        sync_account=_lunar_sync,
    ),
    "paypal": Provider(
        slug="paypal",
        aspsp_name="PayPal",
        aspsp_country="DE",
        default_currency="EUR",
        account_fallback="PayPal payment details",
        psu_type="personal",
        data_role="payment_detail",
        request_balances=False,
        request_transactions=True,
        sync_account=_paypal_sync,
    ),
}


def get_provider(slug: str) -> Provider | None:
    """Return the provider for ``slug`` or ``None`` if unknown."""
    return _PROVIDERS.get(slug)


def all_providers() -> list[Provider]:
    """Return every supported provider in registration order."""
    return list(_PROVIDERS.values())


__all__ = ["Provider", "all_providers", "get_provider"]
