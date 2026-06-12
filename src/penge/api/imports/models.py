"""Response and request models for the import-session endpoints.

Same conventions as :mod:`penge.api.models`: every response model is
frozen, ``payload`` dictionaries carry the parser models' JSON dumps
(Decimals as strings), and timestamps serialise as ISO-8601.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class RowIssue(_Frozen):
    """One validation or duplicate finding on a staged row."""

    code: str
    detail: str


class ImportRowOut(_Frozen):
    """One staged row of an import session."""

    id: uuid.UUID
    row_index: int
    kind: str
    payload: dict[str, object]
    status: str
    issues: list[RowIssue]
    edited: bool
    excluded: bool
    mappings: dict[str, str]
    suggested_by: str | None
    accepted_at: datetime | None


class RowCounts(_Frozen):
    """Aggregated review state of a session's rows."""

    total: int
    ok: int
    warning: int
    error: int
    excluded: int


class ImportSessionOut(_Frozen):
    """One import session without its rows."""

    id: uuid.UUID
    source: str
    original_filename: str
    content_sha256: str
    status: str
    params: dict[str, object]
    error: str | None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    committed_at: datetime | None
    row_counts: RowCounts


class ImportSessionWithRows(ImportSessionOut):
    """One import session plus one page of its rows."""

    rows: list[ImportRowOut]
    total_rows: int


class ImportSessionListResponse(_Frozen):
    """One page of import sessions, newest first."""

    sessions: list[ImportSessionOut]
    total: int


class RowPatchRequest(BaseModel):
    """Corrections to one staged row before commit."""

    payload: dict[str, object] | None = None
    excluded: bool | None = None
    mappings: dict[str, str] | None = None
    suggested_by: str | None = None


MAPPING_FIELDS = ("category", "counterparty", "asset_class")
MAX_MAPPING_VALUE_LENGTH = 500


class MappingSuggestionOut(_Frozen):
    """One AI mapping suggestion for one staged row (ADR-0038)."""

    row_id: uuid.UUID
    row_index: int
    kind: str
    field: str
    value: str
    confidence: float
    reason: str


class SuggestionSessionOut(_Frozen):
    """Session echo returned by the MCP suggestion tool."""

    id: uuid.UUID
    source: str
    status: str
    rows_considered: int


class SuggestionsResponse(_Frozen):
    """Mapping suggestions for one staged session, as returned by MCP."""

    suggested_by: str
    session: SuggestionSessionOut
    suggestions: list[MappingSuggestionOut]


class CommitRequest(BaseModel):
    """Optional commit-time parameters (override upload-time values)."""

    entity_name: str | None = None
    account_name: str | None = None


class CommitCountsOut(_Frozen):
    """Rows written by a commit, in loader vocabulary."""

    entities: int
    accounts: int
    instruments: int
    transactions: int
    holding_snapshots: int


class CommitResponse(_Frozen):
    """Result of committing a session."""

    session: ImportSessionOut
    counts: CommitCountsOut
