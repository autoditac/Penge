"""Parse uploaded files into staged rows with validation and dup flags.

One function per source turns a stored upload into session params
(file-level metadata) plus :class:`~penge.api.imports.store.StagedRow`
records. ``revalidate_payload`` re-runs the same checks for a single
corrected row (the PATCH path).

Payloads are the parser models' ``model_dump(mode="json")`` output:
``Decimal`` round-trips as a string, so amounts never pass through
binary floats on their way into the ``import_row.payload`` JSONB.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from penge.api.imports import store
from penge.api.imports.detect import (
    SOURCE_GROWNEY,
    SOURCE_MANUAL_BALANCES,
    SOURCE_NORDNET_TRANSACTIONS,
    SOURCE_PFA,
)

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.engine import Engine

ROW_KIND_TRANSACTION = "transaction"
ROW_KIND_HOLDING = "holding"
ROW_KIND_SCHEME = "scheme"
ROW_KIND_BALANCE = "balance"


class ImportStagingError(Exception):
    """The uploaded file could not be parsed into staged rows."""


class ManualBalance(BaseModel):
    """One manual cash-balance entry from a ``manual_balances`` JSON file.

    Mirrors the validation of :class:`penge.manual.entries.BalanceEntry`
    so a staged row that validates here also constructs the real entry
    at commit time.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=False)

    entity: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    account_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    currency: Annotated[
        str,
        StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Za-z]{3}$"),
    ]
    as_of: date
    balance: Decimal = Field(..., ge=0, allow_inf_nan=False)
    note: str | None = None


class ManualBalancesFile(BaseModel):
    """Top-level shape of a ``manual_balances`` upload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    balances: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class StagingResult:
    """Everything staged from one uploaded file."""

    params: dict[str, object]
    rows: list[store.StagedRow]


def _duplicate_issue(external_id: str) -> dict[str, str]:
    return {
        "code": "duplicate",
        "detail": (
            f"a transaction with external id {external_id!r} already exists "
            "for this account; committing will idempotently update it"
        ),
    }


def _validation_issues(error: ValidationError) -> list[dict[str, str]]:
    return [
        {
            "code": "invalid",
            "detail": "{}: {}".format(".".join(str(loc) for loc in e["loc"]) or "<root>", e["msg"]),
        }
        for e in error.errors()
    ]


# --------------------------------------------------------------------------- #
# Nordnet transactions CSV
# --------------------------------------------------------------------------- #


def _stage_nordnet(engine: Engine, path: Path) -> StagingResult:
    from penge.ingest.nordnet.loader import PROVIDER as NORDNET_PROVIDER
    from penge.ingest.nordnet.parser import parse_transactions

    try:
        parsed = list(parse_transactions(path))
    except (ValueError, UnicodeError) as exc:
        raise ImportStagingError(f"could not parse Nordnet transactions CSV: {exc}") from exc

    dup_ids_by_account: dict[str, set[str]] = {}
    for account_number in {t.account_number for t in parsed}:
        candidates = [t.nordnet_id for t in parsed if t.account_number == account_number]
        dup_ids_by_account[account_number] = store.existing_transaction_external_ids(
            engine,
            provider=NORDNET_PROVIDER,
            account_external_id=account_number,
            candidate_ids=candidates,
        )

    rows: list[store.StagedRow] = []
    for index, txn in enumerate(parsed):
        issues: list[dict[str, str]] = []
        status = store.ROW_STATUS_OK
        if txn.nordnet_id in dup_ids_by_account[txn.account_number]:
            issues.append(_duplicate_issue(txn.nordnet_id))
            status = store.ROW_STATUS_WARNING
        rows.append(
            store.StagedRow(
                row_index=index,
                kind=ROW_KIND_TRANSACTION,
                payload=txn.model_dump(mode="json"),
                status=status,
                issues=issues,
            )
        )
    return StagingResult(params={}, rows=rows)


# --------------------------------------------------------------------------- #
# Growney / Sutor Depotauszug PDF
# --------------------------------------------------------------------------- #


def _growney_external_id(depot_number: str, payload: dict[str, object]) -> str:
    """Synthesize the loader's external id for one staged transaction."""
    from penge.ingest.growney.models import ParsedTransaction
    from penge.ingest.growney.parser import synthesize_external_id

    txn = ParsedTransaction.model_validate(payload)
    return synthesize_external_id(
        depot_number=depot_number,
        bookkeeping_date=txn.bookkeeping_date,
        value_date=txn.value_date,
        sutor_type=txn.sutor_type,
        isin=txn.isin,
        quantity=txn.quantity,
        net_amount_eur=txn.net_amount_eur,
        description=txn.description,
    )


def _stage_growney(engine: Engine, path: Path) -> StagingResult:
    from penge.ingest.growney.loader import PROVIDER as GROWNEY_PROVIDER
    from penge.ingest.growney.parser import parse_depotauszug, synthesize_external_id

    try:
        parsed = parse_depotauszug(path)
    except (ValueError, KeyError) as exc:
        raise ImportStagingError(f"could not parse Sutor Depotauszug PDF: {exc}") from exc

    external_ids = [
        synthesize_external_id(
            depot_number=parsed.depot_number,
            bookkeeping_date=t.bookkeeping_date,
            value_date=t.value_date,
            sutor_type=t.sutor_type,
            isin=t.isin,
            quantity=t.quantity,
            net_amount_eur=t.net_amount_eur,
            description=t.description,
        )
        for t in parsed.transactions
    ]
    existing = store.existing_transaction_external_ids(
        engine,
        provider=GROWNEY_PROVIDER,
        account_external_id=parsed.depot_number,
        candidate_ids=external_ids,
    )

    params = parsed.model_dump(mode="json")
    params.pop("transactions", None)
    params.pop("holdings", None)

    rows: list[store.StagedRow] = []
    for txn, external_id in zip(parsed.transactions, external_ids, strict=True):
        issues: list[dict[str, str]] = []
        status = store.ROW_STATUS_OK
        if external_id in existing:
            issues.append(_duplicate_issue(external_id))
            status = store.ROW_STATUS_WARNING
        rows.append(
            store.StagedRow(
                row_index=len(rows),
                kind=ROW_KIND_TRANSACTION,
                payload=txn.model_dump(mode="json"),
                status=status,
                issues=issues,
            )
        )
    for holding in parsed.holdings:
        rows.append(
            store.StagedRow(
                row_index=len(rows),
                kind=ROW_KIND_HOLDING,
                payload=holding.model_dump(mode="json"),
                status=store.ROW_STATUS_OK,
                issues=[],
            )
        )
    return StagingResult(params=params, rows=rows)


# --------------------------------------------------------------------------- #
# PFA Pensionsoversigt PDF
# --------------------------------------------------------------------------- #


def _stage_pfa(engine: Engine, path: Path) -> StagingResult:
    from penge.ingest.pfa.parser import parse_pensionsoversigt

    _ = engine  # PFA rows are snapshot upserts; no duplicate probe needed.
    try:
        parsed = parse_pensionsoversigt(path)
    except (ValueError, KeyError) as exc:
        raise ImportStagingError(f"could not parse PFA Pensionsoversigt PDF: {exc}") from exc

    params = parsed.model_dump(mode="json")
    params.pop("schemes", None)

    rows = [
        store.StagedRow(
            row_index=index,
            kind=ROW_KIND_SCHEME,
            payload=scheme.model_dump(mode="json"),
            status=store.ROW_STATUS_OK,
            issues=[],
        )
        for index, scheme in enumerate(parsed.schemes)
    ]
    return StagingResult(params=params, rows=rows)


# --------------------------------------------------------------------------- #
# Manual balances JSON
# --------------------------------------------------------------------------- #


def _stage_manual(engine: Engine, path: Path) -> StagingResult:
    import json

    _ = engine  # balance snapshots upsert idempotently; nothing to probe
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ImportStagingError(f"could not parse manual balances JSON: {exc}") from exc
    try:
        balances_file = ManualBalancesFile.model_validate(document)
    except ValidationError as exc:
        raise ImportStagingError(f"unexpected manual balances shape: {exc}") from exc

    rows: list[store.StagedRow] = []
    for index, raw in enumerate(balances_file.balances):
        # Invalid entries become error rows the client can PATCH-fix,
        # instead of failing the whole upload.
        try:
            entry = ManualBalance.model_validate(raw)
        except ValidationError as exc:
            rows.append(
                store.StagedRow(
                    row_index=index,
                    kind=ROW_KIND_BALANCE,
                    payload={str(k): v for k, v in raw.items()},
                    status=store.ROW_STATUS_ERROR,
                    issues=_validation_issues(exc),
                )
            )
            continue
        rows.append(
            store.StagedRow(
                row_index=index,
                kind=ROW_KIND_BALANCE,
                payload=entry.model_dump(mode="json"),
                status=store.ROW_STATUS_OK,
                issues=[],
            )
        )
    return StagingResult(params={}, rows=rows)


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #


def stage_file(engine: Engine, *, source: str, path: Path) -> StagingResult:
    """Parse one stored upload into session params plus staged rows."""
    if source == SOURCE_NORDNET_TRANSACTIONS:
        return _stage_nordnet(engine, path)
    if source == SOURCE_GROWNEY:
        return _stage_growney(engine, path)
    if source == SOURCE_PFA:
        return _stage_pfa(engine, path)
    if source == SOURCE_MANUAL_BALANCES:
        return _stage_manual(engine, path)
    raise ImportStagingError(f"unknown import source {source!r}")


def _payload_model(source: str, kind: str) -> type[BaseModel]:
    """Return the parser model that validates one (source, kind) payload."""
    if source == SOURCE_NORDNET_TRANSACTIONS and kind == ROW_KIND_TRANSACTION:
        from penge.ingest.nordnet.models import ParsedTransaction as NordnetTransaction

        return NordnetTransaction
    if source == SOURCE_GROWNEY and kind == ROW_KIND_TRANSACTION:
        from penge.ingest.growney.models import ParsedTransaction as GrowneyTransaction

        return GrowneyTransaction
    if source == SOURCE_GROWNEY and kind == ROW_KIND_HOLDING:
        from penge.ingest.growney.models import ParsedHolding as GrowneyHolding

        return GrowneyHolding
    if source == SOURCE_PFA and kind == ROW_KIND_SCHEME:
        from penge.ingest.pfa.models import ParsedScheme

        return ParsedScheme
    if source == SOURCE_MANUAL_BALANCES and kind == ROW_KIND_BALANCE:
        return ManualBalance
    raise ImportStagingError(f"no payload model for source {source!r} row kind {kind!r}")


def revalidate_payload(
    engine: Engine,
    *,
    source: str,
    kind: str,
    session_params: dict[str, object],
    payload: dict[str, object],
) -> tuple[str, list[dict[str, str]], dict[str, object]]:
    """Validate one corrected payload; return (status, issues, normalised).

    Runs the same model validation as staging plus, for transaction
    rows, the duplicate probe against the raw tables.
    """
    model = _payload_model(source, kind)
    try:
        record = model.model_validate(payload)
    except ValidationError as exc:
        return store.ROW_STATUS_ERROR, _validation_issues(exc), payload

    normalised = record.model_dump(mode="json")
    issues: list[dict[str, str]] = []
    status = store.ROW_STATUS_OK

    if source == SOURCE_NORDNET_TRANSACTIONS and kind == ROW_KIND_TRANSACTION:
        from penge.ingest.nordnet.loader import PROVIDER as NORDNET_PROVIDER

        external_id = str(normalised["nordnet_id"])
        account_number = str(normalised["account_number"])
        existing = store.existing_transaction_external_ids(
            engine,
            provider=NORDNET_PROVIDER,
            account_external_id=account_number,
            candidate_ids=[external_id],
        )
        if external_id in existing:
            issues.append(_duplicate_issue(external_id))
            status = store.ROW_STATUS_WARNING
    elif source == SOURCE_GROWNEY and kind == ROW_KIND_TRANSACTION:
        from penge.ingest.growney.loader import PROVIDER as GROWNEY_PROVIDER

        depot_number = str(session_params.get("depot_number", ""))
        external_id = _growney_external_id(depot_number, normalised)
        existing = store.existing_transaction_external_ids(
            engine,
            provider=GROWNEY_PROVIDER,
            account_external_id=depot_number,
            candidate_ids=[external_id],
        )
        if external_id in existing:
            issues.append(_duplicate_issue(external_id))
            status = store.ROW_STATUS_WARNING

    return status, issues, normalised
