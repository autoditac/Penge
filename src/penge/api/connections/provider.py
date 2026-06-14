"""Registry of the Enable Banking ASPSPs Penge can connect to.

Each provider binds a Penge slug to its Enable Banking ASPSP
identity and to the connector's ``load_account`` wrapper, so the
service layer can link / sync any of them through one code path while
preserving per-bank behaviour (e.g. Lunar's Aktiesparekonto
auto-detection).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from penge.ingest.ebank import loader as ebank_loader
from penge.ingest.gls import loader as gls_loader
from penge.ingest.lunar import loader as lunar_loader

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
    sync_account: _SyncAccount


def _gls_sync(
    engine: Engine,
    *,
    client: Client,
    account: AccountResource,
    entity_name: str,
    date_from: date,
    date_to: date,
) -> LoadResult:
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
    entity_name: str,
    date_from: date,
    date_to: date,
) -> LoadResult:
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
    entity_name: str,
    date_from: date,
    date_to: date,
) -> LoadResult:
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


_PROVIDERS: dict[str, Provider] = {
    "gls": Provider(
        slug="gls",
        aspsp_name="GLS Gemeinschaftsbank",
        aspsp_country="DE",
        default_currency="EUR",
        account_fallback="GLS account",
        sync_account=_gls_sync,
    ),
    "ebank": Provider(
        slug="ebank",
        aspsp_name="Evangelische Bank",
        aspsp_country="DE",
        default_currency="EUR",
        account_fallback="Evangelische Bank account",
        sync_account=_ebank_sync,
    ),
    "lunar": Provider(
        slug="lunar",
        aspsp_name="Lunar",
        aspsp_country="DK",
        default_currency="DKK",
        account_fallback="Lunar account",
        sync_account=_lunar_sync,
    ),
}


def get_provider(slug: str) -> Provider | None:
    """Return the provider for ``slug`` or ``None`` if unknown."""
    return _PROVIDERS.get(slug)


def all_providers() -> list[Provider]:
    """Return every supported provider in registration order."""
    return list(_PROVIDERS.values())


__all__ = ["Provider", "all_providers", "get_provider"]
