"""DB-free regression for typed optional search parameters in both page queries."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest

from penge.api import data

if TYPE_CHECKING:
    from collections.abc import Mapping


@pytest.mark.parametrize("search", [None, "SYNTHETIC MARKET"])
def test_optional_search_is_typed_in_page_and_count_queries(
    monkeypatch: pytest.MonkeyPatch,
    search: str | None,
) -> None:
    calls: list[tuple[str, Mapping[str, object]]] = []

    def rows(sql: str, params: Mapping[str, object]) -> list[dict[str, object]]:
        calls.append((sql, params))
        return []

    def count(sql: str, params: Mapping[str, object]) -> int:
        calls.append((sql, params))
        return 0

    monkeypatch.setattr(data, "_rows", rows)
    monkeypatch.setattr(data, "_count", count)
    assert data.fetch_household_transaction_page(
        since=date(2026, 6, 2),
        until=date(2026, 6, 2),
        account_ids=["synthetic-account"],
        entity_ids=[],
        category_ids=[],
        category_filter=False,
        search=search,
        limit=50,
        offset=0,
    ) == ([], 0)

    assert len(calls) == 2
    for sql, params in calls:
        assert "cast(:search as text) is null" in sql
        assert sql.count("lower(cast(:search as text))") == 2
        assert ":search is null" not in sql
        assert params["search"] == (search.casefold() if search is not None else None)
