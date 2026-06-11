"""Engine configuration contract: the read API must be read-only."""

from __future__ import annotations

import pytest

from penge.api import data


@pytest.fixture(autouse=True)
def _fresh_engine_cache() -> None:
    data.get_engine.cache_clear()


def test_engine_opens_read_only_transactions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Accidental DML must fail loudly even with write-capable credentials."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://penge:x@127.0.0.1:1/penge")
    engine = data.get_engine()
    try:
        assert engine.get_execution_options().get("postgresql_readonly") is True
    finally:
        engine.dispose()
        data.get_engine.cache_clear()
