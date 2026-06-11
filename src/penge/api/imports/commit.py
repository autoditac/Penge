"""Commit a staged session into the raw tables via the existing loaders.

The commit path is intentionally thin: re-validate every included
row through the same parser models, reassemble the per-source record
structures, and hand them to the loaders' ``load_records`` — the
exact code path the CLI ingests use. Loader writes run in one
transaction per loader call; a failure rolls back and the session
stays staged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import ValidationError

from penge.api.imports import config, staging
from penge.api.imports.detect import (
    SOURCE_GROWNEY,
    SOURCE_MANUAL_BALANCES,
    SOURCE_NORDNET_TRANSACTIONS,
    SOURCE_PFA,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.engine import Engine

    from penge.api.imports.store import RowRecord, SessionRecord


class ImportCommitError(Exception):
    """The session cannot be committed in its current state."""


@dataclass(frozen=True, slots=True)
class CommitCounts:
    """Rows written by one commit, in loader vocabulary."""

    entities: int
    accounts: int
    instruments: int
    transactions: int
    holding_snapshots: int


def _included(rows: Sequence[RowRecord]) -> list[RowRecord]:
    return [r for r in rows if not r.excluded]


def _require_entity_name(session: SessionRecord, entity_name: str | None) -> str:
    resolved = entity_name or str(session.params.get("entity_name") or "")
    if not resolved:
        raise ImportCommitError(
            "entity_name is required to commit this session; supply it on "
            "upload or in the commit request"
        )
    return resolved


def _commit_nordnet(engine: Engine, rows: Sequence[RowRecord]) -> CommitCounts:
    from penge.ingest.nordnet.config import load_accounts_config
    from penge.ingest.nordnet.loader import UnknownAccountError, load_records
    from penge.ingest.nordnet.models import ParsedTransaction

    config_path = config.nordnet_accounts_config_path()
    if config_path is None:
        raise ImportCommitError(
            "PENGE_NORDNET_ACCOUNTS_CONFIG is not set; the Nordnet accounts "
            "YAML is required to commit Nordnet sessions"
        )
    try:
        accounts_config = load_accounts_config(config_path)
    except (OSError, ValueError) as exc:
        raise ImportCommitError(f"could not load Nordnet accounts config: {exc}") from exc

    transactions = [ParsedTransaction.model_validate(r.payload) for r in rows]
    try:
        result = load_records(
            engine,
            transactions=transactions,
            holdings=[],
            accounts_config=accounts_config,
        )
    except UnknownAccountError as exc:
        raise ImportCommitError(str(exc)) from exc
    return CommitCounts(
        entities=result.entities,
        accounts=result.accounts,
        instruments=result.instruments,
        transactions=result.transactions,
        holding_snapshots=result.holding_snapshots,
    )


def _commit_growney(
    engine: Engine,
    session: SessionRecord,
    rows: Sequence[RowRecord],
    *,
    entity_name: str | None,
    account_name: str | None,
) -> CommitCounts:
    from penge.ingest.growney.loader import load_records
    from penge.ingest.growney.models import ParsedDepotauszug

    resolved_entity = _require_entity_name(session, entity_name)
    stored_account = session.params.get("account_name")
    resolved_account = account_name or (str(stored_account) if stored_account else None)
    depotauszug = ParsedDepotauszug.model_validate(
        {
            **session.params,
            "transactions": [r.payload for r in rows if r.kind == staging.ROW_KIND_TRANSACTION],
            "holdings": [r.payload for r in rows if r.kind == staging.ROW_KIND_HOLDING],
        }
    )
    result = load_records(
        engine,
        depotauszuege=[depotauszug],
        entity_name=resolved_entity,
        account_name=resolved_account,
    )
    return CommitCounts(
        entities=result.entities,
        accounts=result.accounts,
        instruments=result.instruments,
        transactions=result.transactions,
        holding_snapshots=result.holding_snapshots,
    )


def _commit_pfa(
    engine: Engine,
    session: SessionRecord,
    rows: Sequence[RowRecord],
    *,
    entity_name: str | None,
) -> CommitCounts:
    from penge.ingest.pfa.loader import load_records
    from penge.ingest.pfa.models import ParsedPensionsoversigt

    resolved_entity = _require_entity_name(session, entity_name)
    statement = ParsedPensionsoversigt.model_validate(
        {
            **session.params,
            "schemes": [r.payload for r in rows if r.kind == staging.ROW_KIND_SCHEME],
        }
    )
    result = load_records(engine, statements=[statement], entity_name=resolved_entity)
    return CommitCounts(
        entities=result.entities,
        accounts=result.accounts,
        instruments=result.instruments,
        transactions=result.transactions,
        holding_snapshots=result.holding_snapshots,
    )


def _commit_manual(engine: Engine, rows: Sequence[RowRecord]) -> CommitCounts:
    from penge.manual.entries import BalanceEntry
    from penge.manual.service import record_cash_balance

    entries: list[BalanceEntry] = []
    for row in rows:
        balance = staging.ManualBalance.model_validate(row.payload)
        entries.append(
            BalanceEntry(
                entity=balance.entity,
                account_name=balance.account_name,
                currency=balance.currency,
                as_of=balance.as_of,
                balance=balance.balance,
                note=balance.note,
            )
        )
    # record_cash_balance runs one transaction per entry. The upsert is
    # idempotent on (account, instrument, as_of), so re-committing after
    # a mid-list failure converges instead of double-counting.
    for entry in entries:
        record_cash_balance(engine, entry)
    return CommitCounts(
        entities=0,
        accounts=0,
        instruments=0,
        transactions=0,
        holding_snapshots=len(entries),
    )


def commit_session(
    engine: Engine,
    session: SessionRecord,
    rows: Sequence[RowRecord],
    *,
    entity_name: str | None = None,
    account_name: str | None = None,
) -> CommitCounts:
    """Write all included rows of one staged session to the raw tables."""
    included = _included(rows)
    error_rows = [r for r in included if r.status == "error"]
    if error_rows:
        indices = ", ".join(str(r.row_index) for r in error_rows[:10])
        raise ImportCommitError(
            f"session has {len(error_rows)} error row(s) (row_index: {indices}); "
            "fix them via PATCH or exclude them before committing"
        )
    if not included:
        raise ImportCommitError("session has no included rows to commit")

    try:
        if session.source == SOURCE_NORDNET_TRANSACTIONS:
            return _commit_nordnet(engine, included)
        if session.source == SOURCE_GROWNEY:
            return _commit_growney(
                engine,
                session,
                included,
                entity_name=entity_name,
                account_name=account_name,
            )
        if session.source == SOURCE_PFA:
            return _commit_pfa(engine, session, included, entity_name=entity_name)
        if session.source == SOURCE_MANUAL_BALANCES:
            return _commit_manual(engine, included)
    except ValidationError as exc:
        raise ImportCommitError(f"staged rows failed re-validation: {exc}") from exc
    except ValueError as exc:
        raise ImportCommitError(str(exc)) from exc
    raise ImportCommitError(f"unknown import source {session.source!r}")
