"""DB-free regressions for synthetic fixture and migration process isolation."""

import logging
import os
from unittest.mock import Mock

import pytest

from tests.household.database_setup import upgrade_isolated_database
from tests.household.fixtures import BANK_ENTRIES


def test_all_source_descriptions_are_explicitly_synthetic() -> None:
    assert all("Synthetic" in entry.description for entry in BANK_ENTRIES)


def test_migration_does_not_reconfigure_parent_logging_or_environment(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    url = "postgresql+psycopg://synthetic:synthetic@127.0.0.1/penge_household_test"
    runner = Mock()
    monkeypatch.setattr("tests.household.database_setup.subprocess.run", runner)
    monkeypatch.setenv("PENGE_ALLOW_DESTRUCTIVE_TEST_DB", "1")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    handlers = tuple(logging.getLogger().handlers)
    logger = logging.getLogger("penge.ops.heartbeat")
    disabled = logger.disabled

    upgrade_isolated_database(url)

    assert runner.call_count == 1
    assert runner.call_args.args[0][-3:] == ["alembic", "upgrade", "head"]
    assert runner.call_args.kwargs["env"]["DATABASE_URL"] == url
    assert runner.call_args.kwargs["check"] is True
    assert "DATABASE_URL" not in os.environ
    assert tuple(logging.getLogger().handlers) == handlers
    assert logger.disabled == disabled
    with caplog.at_level(logging.WARNING, logger.name):
        logger.warning("synthetic migration logging regression")
    assert any("synthetic migration logging regression" in row.message for row in caplog.records)


def test_migration_rejects_non_disposable_database_before_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = Mock()
    monkeypatch.setattr("tests.household.database_setup.subprocess.run", runner)
    monkeypatch.setenv("PENGE_ALLOW_DESTRUCTIVE_TEST_DB", "1")
    with pytest.raises(ValueError):
        upgrade_isolated_database("postgresql+psycopg://localhost/penge")
    runner.assert_not_called()
