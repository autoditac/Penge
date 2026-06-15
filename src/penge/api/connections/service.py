"""Service layer: link / authorize / sync orchestration.

Wraps the Enable Banking client and the per-bank connectors, persists
connection state, and converts upstream failures into a small set of
typed errors carrying a **sanitised** debug payload (status code,
machine error code, generic message) — never IBANs, names, or amounts.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

from penge.api.connections import store
from penge.api.connections.provider import get_provider
from penge.ingest.enablebanking.client import EnableBankingError, default_consent_until
from penge.web.mask import mask_iban

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

    from penge.api.connections.provider import Provider
    from penge.ingest.enablebanking.client import Client
    from penge.ingest.enablebanking.models import AccountResource

log = logging.getLogger("penge.api.connections")

DEFAULT_CONSENT_DAYS = 180
DEFAULT_HISTORY_DAYS = 365

# Enable Banking error code an ASPSP returns when the requested
# ``date_from`` reaches further back than it currently permits. Under
# PSD2 a bank typically serves the full history only on the first access
# right after Strong Customer Authentication, then limits unattended
# repeat access to a shorter window (commonly 90 days). We fall back to
# progressively narrower windows so a routine sync keeps the connection
# up to date; older history is already persisted from the initial sync
# and the transaction upsert is idempotent, so nothing is lost.
WRONG_TRANSACTIONS_PERIOD = "WRONG_TRANSACTIONS_PERIOD"
HISTORY_FALLBACK_DAYS: tuple[int, ...] = (90, 30)

_SESSION_AUTHORIZED = "AUTHORIZED"


@dataclass(frozen=True, slots=True)
class ConnectionError(Exception):
    """A link/authorize/sync failure with a sanitised debug payload."""

    step: str
    message: str
    status_code: int | None = None
    code: str | None = None
    not_found: bool = False

    def as_error_payload(self) -> dict[str, object]:
        """Serialise for the ``last_error`` JSONB column."""
        payload: dict[str, object] = {
            "step": self.step,
            "message": self.message,
            "at": datetime.now(UTC).isoformat(),
        }
        if self.status_code is not None:
            payload["status_code"] = self.status_code
        if self.code is not None:
            payload["code"] = self.code
        return payload


def _eb_message(body: object) -> tuple[str | None, str]:
    """Extract ``(error_code, message)`` from an Enable Banking error body."""
    if isinstance(body, dict):
        code = body.get("error")
        message = body.get("message") or body.get("detail") or "Enable Banking error"
        return (str(code) if code is not None else None, str(message))
    return (None, str(body))


def _from_eb_error(step: str, exc: EnableBankingError) -> ConnectionError:
    code, message = _eb_message(exc.body)
    return ConnectionError(
        step=step,
        message=message,
        status_code=exc.status_code,
        code=code,
    )


def _account_snapshot(accounts: list[AccountResource]) -> list[dict[str, object]]:
    """Build the non-sensitive account snapshot stored on the connection."""
    snapshot: list[dict[str, object]] = []
    for acct in accounts:
        iban = acct.account_id.iban if acct.account_id else None
        snapshot.append(
            {
                "name": acct.name,
                "iban_masked": mask_iban(iban) or None,
                "currency": acct.currency,
                "product": acct.product,
            }
        )
    return snapshot


def start_link(
    engine: Engine,
    client: Client,
    *,
    redirect_url: str,
    provider_slug: str,
    entity_name: str,
) -> tuple[store.ConnectionRecord, str]:
    """Begin a consent: persist a ``linking`` row and return the consent URL."""
    provider = get_provider(provider_slug)
    if provider is None:
        raise ConnectionError(step="link", message=f"unknown provider '{provider_slug}'")

    state = str(uuid.uuid4())
    valid_until = default_consent_until(days=DEFAULT_CONSENT_DAYS)
    try:
        resp = client.start_authorization(
            aspsp_name=provider.aspsp_name,
            aspsp_country=provider.aspsp_country,
            redirect_url=redirect_url,
            valid_until=valid_until,
            state=state,
        )
    except EnableBankingError as exc:
        raise _from_eb_error("link", exc) from exc

    record = store.create_linking(
        engine,
        provider=provider.slug,
        aspsp_name=provider.aspsp_name,
        aspsp_country=provider.aspsp_country,
        entity_name=entity_name,
        state=state,
        authorization_id=resp.authorization_id,
        valid_until=valid_until,
    )
    log.info("connection link started provider=%s id=%s", provider.slug, record.id)
    return record, resp.url


def _resolve_pending(
    engine: Engine,
    *,
    state: str | None,
    aspsp_name: str,
) -> store.ConnectionRecord | None:
    """Find the ``linking`` connection a callback code belongs to.

    Prefers the CSRF ``state`` (exact match). When the callback did not
    carry state, fall back to a pending connection for the same ASPSP
    **only when exactly one** is in-flight: with several concurrent
    links for the same bank, guessing could bind the code to the wrong
    connection, so the caller is required to supply ``state`` instead.
    """
    if state:
        return store.get_by_state(engine, state)
    candidates = [
        record
        for record in store.list_connections(engine)
        if record.status == store.STATUS_LINKING and record.aspsp_name == aspsp_name
    ]
    if len(candidates) == 1:
        return candidates[0]
    return None


def authorize(
    engine: Engine,
    client: Client,
    *,
    code: str,
    state: str | None,
) -> store.ConnectionRecord:
    """Exchange the redirect ``code`` for a session and persist it.

    The Enable Banking ``code`` is single-use: ``POST /sessions`` consumes
    it and a second exchange returns ``ALREADY_AUTHORIZED``. When the caller
    supplies the CSRF ``state`` we therefore bind it to the pending
    connection **before** spending the code, so a mismatched or stale state
    fails without burning the code (which would otherwise orphan the EB
    session and leave the connection un-recoverable). Only a row that is
    still ``linking`` counts as pending: ``record_error`` keeps the old
    ``state`` on failed rows, so without this guard a stale ``error`` row
    could match a freshly issued code, spend it, and bind the session to the
    wrong (non-linking) connection. The stateless fallback still has to call
    EB first, because the ASPSP name needed to disambiguate concurrent links
    is only known from the session response.
    """
    pending = store.get_by_state(engine, state) if state else None
    if pending is not None and pending.status != store.STATUS_LINKING:
        pending = None
    if state and pending is None:
        raise ConnectionError(
            step="authorize",
            message="no pending connection matched this consent state",
            not_found=True,
        )

    try:
        resp = client.authorize_session(code)
    except EnableBankingError as exc:
        err = _from_eb_error("authorize", exc)
        if pending is not None:
            store.record_error(engine, pending.id, error=err.as_error_payload())
        raise err from exc

    if pending is None:
        pending = _resolve_pending(engine, state=None, aspsp_name=resp.aspsp.name)
    if pending is None:
        raise ConnectionError(
            step="authorize",
            message=(
                "could not unambiguously match this consent; retry with the "
                "?state= value from the callback"
            ),
            not_found=True,
        )

    record = store.mark_authorized(
        engine,
        pending.id,
        session_id=resp.session_id,
        valid_until=resp.access.valid_until,
        accounts=_account_snapshot(resp.accounts),
    )
    log.info("connection authorized provider=%s id=%s", record.provider, record.id)
    return record


@dataclass(frozen=True, slots=True)
class SyncOutcome:
    """Counts produced by a sync run."""

    record: store.ConnectionRecord
    transactions: int
    holding_snapshots: int


def _history_windows(days: int) -> list[int]:
    """The requested window plus any strictly narrower fallback windows.

    Used to recover from an ASPSP rejecting an over-long ``date_from``
    with ``WRONG_TRANSACTIONS_PERIOD`` on unattended repeat access.
    """
    return [days, *[w for w in HISTORY_FALLBACK_DAYS if w < days]]


def _sync_accounts(
    engine: Engine,
    provider: Provider,
    *,
    client: Client,
    accounts: list[AccountResource],
    entity_name: str,
    date_from: date,
    date_to: date,
) -> tuple[int, int]:
    """Sync every account for one window, returning ``(txns, snapshots)``.

    Raises :class:`EnableBankingError` unchanged so the caller can decide
    whether to retry with a narrower window or record the failure.
    """
    total_txn = 0
    total_snap = 0
    for acct in accounts:
        result = provider.sync_account(
            engine,
            client=client,
            account=acct,
            entity_name=entity_name,
            date_from=date_from,
            date_to=date_to,
        )
        total_txn += result.transactions
        total_snap += result.holding_snapshots
    return total_txn, total_snap


def sync(
    engine: Engine,
    client: Client,
    *,
    connection_id: uuid.UUID,
    days: int = DEFAULT_HISTORY_DAYS,
) -> SyncOutcome:
    """Pull transactions + balances for every account on the connection."""
    record = store.get_connection(engine, connection_id)
    if record is None:
        raise ConnectionError(step="sync", message="connection not found", not_found=True)

    provider = get_provider(record.provider)
    if provider is None:
        raise ConnectionError(step="sync", message=f"unknown provider '{record.provider}'")

    if not record.session_id:
        err = ConnectionError(step="sync", message="connection is not authorized yet")
        store.record_error(engine, record.id, error=err.as_error_payload(), is_sync=True)
        raise err

    try:
        session = client.get_session(record.session_id)
    except EnableBankingError as exc:
        err = _from_eb_error("sync", exc)
        store.record_error(engine, record.id, error=err.as_error_payload(), is_sync=True)
        raise err from exc

    if session.status != _SESSION_AUTHORIZED:
        err = ConnectionError(
            step="sync",
            message=f"session status is {session.status}; re-consent required",
        )
        store.record_error(
            engine,
            record.id,
            error=err.as_error_payload(),
            status=store.STATUS_EXPIRED,
            is_sync=True,
        )
        raise err

    date_to = datetime.now(UTC).date()
    selected = [a for a in session.accounts_data if a.uid is not None]
    if not selected:
        err = ConnectionError(step="sync", message="no accounts to sync on this session")
        store.record_error(engine, record.id, error=err.as_error_payload(), is_sync=True)
        raise err

    windows = _history_windows(days)
    total_txn = 0
    total_snap = 0
    for index, window in enumerate(windows):
        date_from = (datetime.now(UTC) - timedelta(days=window)).date()
        try:
            total_txn, total_snap = _sync_accounts(
                engine,
                provider,
                client=client,
                accounts=selected,
                entity_name=record.entity_name,
                date_from=date_from,
                date_to=date_to,
            )
        except EnableBankingError as exc:
            code, _ = _eb_message(exc.body)
            is_last = index == len(windows) - 1
            if code == WRONG_TRANSACTIONS_PERIOD and not is_last:
                log.warning(
                    "connection %s: ASPSP rejected %d-day history window, retrying with %d days",
                    record.id,
                    window,
                    windows[index + 1],
                )
                continue
            err = _from_eb_error("sync", exc)
            store.record_error(engine, record.id, error=err.as_error_payload(), is_sync=True)
            raise err from exc
        else:
            if window != days:
                log.warning(
                    "connection %s: synced with reduced %d-day window "
                    "(ASPSP rejected the requested %d days)",
                    record.id,
                    window,
                    days,
                )
            break

    updated = store.record_sync_ok(engine, record.id, accounts=_account_snapshot(selected))
    log.info(
        "connection synced provider=%s id=%s txns=%d snapshots=%d",
        record.provider,
        record.id,
        total_txn,
        total_snap,
    )
    return SyncOutcome(record=updated, transactions=total_txn, holding_snapshots=total_snap)


__all__ = [
    "DEFAULT_CONSENT_DAYS",
    "DEFAULT_HISTORY_DAYS",
    "HISTORY_FALLBACK_DAYS",
    "WRONG_TRANSACTIONS_PERIOD",
    "ConnectionError",
    "SyncOutcome",
    "authorize",
    "start_link",
    "sync",
]
