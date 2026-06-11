"""Route handlers for staged import sessions (issue #207, ADR-0037).

The only write surface in the API. Uploads stream to the gitignored
import directory with a hard size cap, get parsed into staged rows,
and nothing touches the raw tables until an explicit commit. Logs
carry ids and counts — never file contents.
"""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, BinaryIO

from fastapi import APIRouter, Form, HTTPException, Query, UploadFile

from penge.api.imports import commit as commit_mod
from penge.api.imports import config, staging, store
from penge.api.imports.detect import KNOWN_SOURCES, UnsupportedSourceError, detect_source
from penge.api.imports.engine import get_import_engine
from penge.api.imports.models import (
    CommitCountsOut,
    CommitRequest,
    CommitResponse,
    ImportRowOut,
    ImportSessionListResponse,
    ImportSessionOut,
    ImportSessionWithRows,
    RowCounts,
    RowIssue,
    RowPatchRequest,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

log = logging.getLogger("penge.api.imports")

router = APIRouter(prefix="/imports", tags=["imports"])

DEFAULT_ROW_LIMIT = 1_000
MAX_ROW_LIMIT = 10_000

_LimitParam = Annotated[int, Query(ge=1, le=MAX_ROW_LIMIT, description="Page size.")]
_OffsetParam = Annotated[int, Query(ge=0, description="Page start offset.")]

_UPLOAD_CHUNK_BYTES = 1024 * 1024

# Conservative filename allow-list: path separators, control chars and
# anything exotic becomes "_". Spaces, dots, commas, danish/german
# letters survive — provider export names stay recognisable.
_FILENAME_SANITISER = re.compile(r"[^\w .,()\-æøåÆØÅäöüÄÖÜß]")


def _sanitise_filename(raw: str | None) -> str:
    name = Path(raw or "upload").name
    cleaned = _FILENAME_SANITISER.sub("_", name).strip()
    return cleaned or "upload"


def _row_out(row: store.RowRecord) -> ImportRowOut:
    return ImportRowOut(
        id=row.id,
        row_index=row.row_index,
        kind=row.kind,
        payload=row.payload,
        status=row.status,
        issues=[RowIssue(code=i.get("code", ""), detail=i.get("detail", "")) for i in row.issues],
        edited=row.edited,
        excluded=row.excluded,
    )


def _row_counts(rows: Sequence[store.RowRecord]) -> RowCounts:
    return RowCounts(
        total=len(rows),
        ok=sum(1 for r in rows if r.status == store.ROW_STATUS_OK),
        warning=sum(1 for r in rows if r.status == store.ROW_STATUS_WARNING),
        error=sum(1 for r in rows if r.status == store.ROW_STATUS_ERROR),
        excluded=sum(1 for r in rows if r.excluded),
    )


def _session_out(session: store.SessionRecord, rows: Sequence[store.RowRecord]) -> ImportSessionOut:
    return ImportSessionOut(
        id=session.id,
        source=session.source,
        original_filename=session.original_filename,
        content_sha256=session.content_sha256,
        status=session.status,
        params=session.params,
        error=session.error,
        created_at=session.created_at,
        updated_at=session.updated_at,
        expires_at=session.expires_at,
        committed_at=session.committed_at,
        row_counts=_row_counts(rows),
    )


def _stream_to_disk(source: BinaryIO, target: Path, *, max_bytes: int) -> tuple[str, int]:
    """Stream an upload to ``target``; return ``(sha256, size)``.

    Raises 413 (and removes the partial file) past the size cap.
    """
    digest = hashlib.sha256()
    size = 0
    with target.open("wb") as out:
        while True:
            chunk = source.read(_UPLOAD_CHUNK_BYTES)
            if not chunk:
                break
            size += len(chunk)
            if size > max_bytes:
                out.close()
                target.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"upload exceeds the {max_bytes} byte limit",
                )
            digest.update(chunk)
            out.write(chunk)
    return digest.hexdigest(), size


def _load_session(session_id: uuid.UUID) -> store.SessionRecord:
    engine = get_import_engine()
    session = store.get_session(engine, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="import session not found")
    return store.expire_if_stale(engine, session)


def _require_staged(session: store.SessionRecord) -> None:
    if session.status != store.SESSION_STATUS_STAGED:
        raise HTTPException(
            status_code=409,
            detail=f"import session is {session.status}; only staged sessions can be modified",
        )


@router.post("", response_model=ImportSessionWithRows, status_code=201)
def create_import(
    file: UploadFile,
    source: Annotated[str | None, Form()] = None,
    entity_name: Annotated[str | None, Form()] = None,
    account_name: Annotated[str | None, Form()] = None,
) -> ImportSessionWithRows:
    """Upload one statement, parse it, and stage its rows for review."""
    if source is not None and source not in KNOWN_SOURCES:
        raise HTTPException(
            status_code=422,
            detail=f"unknown source {source!r}; expected one of {', '.join(KNOWN_SOURCES)}",
        )

    filename = _sanitise_filename(file.filename)
    session_dir = config.import_dir() / uuid.uuid4().hex
    session_dir.mkdir(parents=True, exist_ok=False)
    stored_path = session_dir / filename

    try:
        sha256, size = _stream_to_disk(file.file, stored_path, max_bytes=config.max_upload_bytes())

        resolved_source = source
        if resolved_source is None:
            try:
                resolved_source = detect_source(stored_path)
            except UnsupportedSourceError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        if resolved_source is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    "could not detect the statement source; pass an explicit "
                    f"source ({', '.join(KNOWN_SOURCES)})"
                ),
            )

        engine = get_import_engine()
        try:
            staged = staging.stage_file(engine, source=resolved_source, path=stored_path)
        except staging.ImportStagingError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        params: dict[str, object] = dict(staged.params)
        if entity_name:
            params["entity_name"] = entity_name
        if account_name:
            params["account_name"] = account_name

        session = store.create_session(
            engine,
            source=resolved_source,
            original_filename=filename,
            content_sha256=sha256,
            stored_path=str(stored_path),
            params=params,
            ttl_days=config.session_ttl_days(),
            rows=staged.rows,
        )
    except Exception:
        shutil.rmtree(session_dir, ignore_errors=True)
        raise

    rows, total = store.get_rows(engine, session.id, limit=DEFAULT_ROW_LIMIT)
    log.info(
        "import session created: id=%s source=%s rows=%d bytes=%d",
        session.id,
        resolved_source,
        total,
        size,
    )
    base = _session_out(session, rows)
    return ImportSessionWithRows(
        **base.model_dump(),
        rows=[_row_out(r) for r in rows],
        total_rows=total,
    )


@router.get("", response_model=ImportSessionListResponse)
def list_imports(
    limit: _LimitParam = DEFAULT_ROW_LIMIT,
    offset: _OffsetParam = 0,
) -> ImportSessionListResponse:
    """List import sessions, newest first."""
    engine = get_import_engine()
    sessions, total = store.list_sessions(engine, limit=limit, offset=offset)
    out: list[ImportSessionOut] = []
    for session in sessions:
        refreshed = store.expire_if_stale(engine, session)
        rows, _ = store.get_rows(engine, refreshed.id)
        out.append(_session_out(refreshed, rows))
    return ImportSessionListResponse(sessions=out, total=total)


@router.get("/{session_id}", response_model=ImportSessionWithRows)
def get_import(
    session_id: uuid.UUID,
    limit: _LimitParam = DEFAULT_ROW_LIMIT,
    offset: _OffsetParam = 0,
) -> ImportSessionWithRows:
    """Return one session with one page of its staged rows."""
    session = _load_session(session_id)
    engine = get_import_engine()
    all_rows, _ = store.get_rows(engine, session.id)
    page, total = store.get_rows(engine, session.id, limit=limit, offset=offset)
    base = _session_out(session, all_rows)
    return ImportSessionWithRows(
        **base.model_dump(),
        rows=[_row_out(r) for r in page],
        total_rows=total,
    )


@router.patch("/{session_id}/rows/{row_id}", response_model=ImportRowOut)
def patch_import_row(
    session_id: uuid.UUID,
    row_id: uuid.UUID,
    request: RowPatchRequest,
) -> ImportRowOut:
    """Correct or exclude one staged row before commit."""
    session = _load_session(session_id)
    _require_staged(session)
    engine = get_import_engine()
    row = store.get_row(engine, session.id, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="import row not found")

    if request.payload is None and request.excluded is None:
        raise HTTPException(
            status_code=422,
            detail="nothing to update; supply payload and/or excluded",
        )

    if request.payload is not None:
        status, issues, normalised = staging.revalidate_payload(
            engine,
            source=session.source,
            kind=row.kind,
            session_params=session.params,
            payload=request.payload,
        )
        row = store.update_row(
            engine,
            row.id,
            payload=normalised,
            status=status,
            issues=issues,
            edited=True,
            excluded=request.excluded,
        )
    else:
        row = store.update_row(engine, row.id, excluded=request.excluded)

    log.info(
        "import row updated: session=%s row=%s status=%s excluded=%s",
        session.id,
        row.id,
        row.status,
        row.excluded,
    )
    return _row_out(row)


@router.post("/{session_id}/commit", response_model=CommitResponse)
def commit_import(
    session_id: uuid.UUID,
    request: CommitRequest | None = None,
) -> CommitResponse:
    """Write all included rows to the raw tables via the loaders."""
    session = _load_session(session_id)
    _require_staged(session)
    engine = get_import_engine()
    rows, _ = store.get_rows(engine, session.id)

    body = request or CommitRequest()
    try:
        counts = commit_mod.commit_session(
            engine,
            session,
            rows,
            entity_name=body.entity_name,
            account_name=body.account_name,
        )
    except commit_mod.ImportCommitError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    committed = store.set_session_status(
        engine, session.id, store.SESSION_STATUS_COMMITTED, committed=True
    )
    log.info(
        "import session committed: id=%s source=%s transactions=%d holding_snapshots=%d",
        committed.id,
        committed.source,
        counts.transactions,
        counts.holding_snapshots,
    )
    return CommitResponse(
        session=_session_out(committed, rows),
        counts=CommitCountsOut(
            entities=counts.entities,
            accounts=counts.accounts,
            instruments=counts.instruments,
            transactions=counts.transactions,
            holding_snapshots=counts.holding_snapshots,
        ),
    )


@router.delete("/{session_id}", response_model=ImportSessionOut)
def discard_import(session_id: uuid.UUID) -> ImportSessionOut:
    """Discard a staged (or expired) session and delete its stored file."""
    session = _load_session(session_id)
    engine = get_import_engine()
    if session.status == store.SESSION_STATUS_COMMITTED:
        raise HTTPException(
            status_code=409,
            detail="committed sessions are kept for audit and cannot be discarded",
        )
    if session.status != store.SESSION_STATUS_DISCARDED:
        session = store.set_session_status(engine, session.id, store.SESSION_STATUS_DISCARDED)
        stored = Path(session.stored_path)
        if stored.parent.is_dir():
            shutil.rmtree(stored.parent, ignore_errors=True)
        log.info("import session discarded: id=%s", session.id)
    rows, _ = store.get_rows(engine, session.id)
    return _session_out(session, rows)
