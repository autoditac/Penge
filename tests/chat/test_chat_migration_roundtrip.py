"""Integration coverage for the dedicated chat OAuth Alembic chain."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

ADMIN_URL_ENV = "PENGE_CHAT_MIGRATION_TEST_ADMIN_URL"
FINANCE_DATABASE = "penge_finance_migration_test"
CHAT_DATABASE = "penge_chat_oauth_migration_test"
EXTERNAL_ROLE = "penge_chat_oauth_migration_test"
STORE_ROLE = "penge_chat_oauth_store_test"
CHAT_TABLES = {"chat_oauth_link", "chat_oauth_state", "chat_audit_event"}


def _synthetic_password(suffix: str) -> str:
    return f"synthetic@{suffix}"


EXTERNAL_ROLE_PASSWORD = _synthetic_password("migration")
STORE_ROLE_PASSWORD = _synthetic_password("store")


def _database_url(
    admin_url: str,
    database: str,
    *,
    username: str | None = None,
    password: str | None = None,
) -> str:
    url = sa.engine.make_url(admin_url)
    return url.set(
        database=database,
        username=username or url.username,
        password=password or url.password,
    ).render_as_string(hide_password=False)


@pytest.fixture
def isolated_databases() -> Iterator[tuple[str, str, str]]:
    """Create isolated finance/chat databases and an externally managed role."""
    admin_url = os.environ.get(ADMIN_URL_ENV)
    if admin_url is None:
        pytest.skip(f"{ADMIN_URL_ENV} is required for the migration integration test")
    engine = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as connection:
        connection.execute(sa.text(f'DROP DATABASE IF EXISTS "{FINANCE_DATABASE}"'))
        connection.execute(sa.text(f'DROP DATABASE IF EXISTS "{CHAT_DATABASE}"'))
        connection.execute(sa.text(f'DROP ROLE IF EXISTS "{EXTERNAL_ROLE}"'))
        connection.execute(sa.text(f'DROP ROLE IF EXISTS "{STORE_ROLE}"'))
        connection.execute(
            sa.text(
                f"""CREATE ROLE "{EXTERNAL_ROLE}" LOGIN
                PASSWORD '{EXTERNAL_ROLE_PASSWORD}'"""
            )
        )
        connection.execute(
            sa.text(f"""CREATE ROLE "{STORE_ROLE}" LOGIN PASSWORD '{STORE_ROLE_PASSWORD}'""")
        )
        connection.execute(sa.text(f'CREATE DATABASE "{FINANCE_DATABASE}"'))
        connection.execute(sa.text(f'CREATE DATABASE "{CHAT_DATABASE}" OWNER "{EXTERNAL_ROLE}"'))
    try:
        yield (
            _database_url(admin_url, FINANCE_DATABASE),
            _database_url(
                admin_url,
                CHAT_DATABASE,
                username=EXTERNAL_ROLE,
                password=EXTERNAL_ROLE_PASSWORD,
            ),
            admin_url,
        )
    finally:
        with engine.connect() as connection:
            connection.execute(sa.text(f'DROP DATABASE IF EXISTS "{FINANCE_DATABASE}"'))
            connection.execute(sa.text(f'DROP DATABASE IF EXISTS "{CHAT_DATABASE}"'))
            connection.execute(sa.text(f'DROP ROLE IF EXISTS "{EXTERNAL_ROLE}"'))
            connection.execute(sa.text(f'DROP ROLE IF EXISTS "{STORE_ROLE}"'))
        engine.dispose()


def _table_names(database_url: str) -> set[str]:
    engine = sa.create_engine(database_url)
    try:
        return set(sa.inspect(engine).get_table_names(schema="public"))
    finally:
        engine.dispose()


def _run_store_postgres_tests(admin_url: str) -> None:
    chat_admin_url = _database_url(admin_url, CHAT_DATABASE)
    chat_admin_engine = sa.create_engine(chat_admin_url)
    try:
        with chat_admin_engine.begin() as connection:
            connection.execute(
                sa.text("CREATE TABLE finance_shadow (id integer PRIMARY KEY, amount numeric)")
            )
            connection.execute(sa.text(f'GRANT USAGE ON SCHEMA public TO "{STORE_ROLE}"'))
            connection.execute(
                sa.text(
                    f"GRANT SELECT, INSERT, UPDATE, DELETE ON "
                    f'chat_oauth_link, chat_oauth_state TO "{STORE_ROLE}"'
                )
            )
            connection.execute(sa.text(f'GRANT INSERT ON chat_audit_event TO "{STORE_ROLE}"'))
            connection.execute(
                sa.text(
                    f'GRANT USAGE, SELECT ON SEQUENCE chat_audit_event_id_seq TO "{STORE_ROLE}"'
                )
            )
            connection.execute(
                sa.text(f'GRANT SELECT (amount) ON finance_shadow TO "{STORE_ROLE}"')
            )
        store_url = _database_url(
            admin_url,
            CHAT_DATABASE,
            username=STORE_ROLE,
            password=STORE_ROLE_PASSWORD,
        )
        pnpm = shutil.which("pnpm")
        assert pnpm is not None
        store_test = subprocess.run(  # noqa: S603 - resolved executable, constant arguments
            [
                pnpm,
                "--filter",
                "@penge/chat",
                "exec",
                "vitest",
                "run",
                "tests/store.postgres.test.ts",
            ],
            check=False,
            capture_output=True,
            env={
                **os.environ,
                "PENGE_CHAT_STORE_TEST_DATABASE_URL": store_url,
                "PENGE_CHAT_STORE_TEST_ROLE": STORE_ROLE,
                "PENGE_CHAT_STORE_EXPECT_PRIVILEGE_REJECTION": "1",
            },
            text=True,
        )
        assert store_test.returncode == 0, store_test.stdout + store_test.stderr
        with chat_admin_engine.begin() as connection:
            connection.execute(sa.text("DROP TABLE finance_shadow"))
        functional_test = subprocess.run(  # noqa: S603 - resolved executable, constant arguments
            [
                pnpm,
                "--filter",
                "@penge/chat",
                "exec",
                "vitest",
                "run",
                "tests/store.postgres.test.ts",
            ],
            check=False,
            capture_output=True,
            env={
                **os.environ,
                "PENGE_CHAT_STORE_TEST_DATABASE_URL": store_url,
                "PENGE_CHAT_STORE_TEST_ADMIN_URL": chat_admin_url,
                "PENGE_CHAT_STORE_TEST_ROLE": STORE_ROLE,
            },
            text=True,
        )
        assert functional_test.returncode == 0, functional_test.stdout + functional_test.stderr
    finally:
        chat_admin_engine.dispose()


def test_dedicated_chat_migration_roundtrip(
    isolated_databases: tuple[str, str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Round-trip chat storage without touching finance schema or role lifecycle."""
    finance_url, chat_url, admin_url = isolated_databases
    assert "%40" in chat_url
    finance_config = Config("alembic.ini")
    monkeypatch.setenv("DATABASE_URL", finance_url)
    command.upgrade(finance_config, "head")
    finance_before = _table_names(finance_url)
    assert finance_before
    assert finance_before.isdisjoint(CHAT_TABLES)

    secret_path = tmp_path / "chat-database-url"
    secret_path.write_text(
        chat_url.replace("postgresql+psycopg://", "postgresql://", 1),
        encoding="utf-8",
    )
    secret_path.chmod(0o600)
    monkeypatch.setenv("PENGE_CHAT_MIGRATION_DATABASE_URL_FILE", str(secret_path))
    chat_config = Config("apps/chat/alembic.ini")
    command.upgrade(chat_config, "head")

    assert _table_names(chat_url) == CHAT_TABLES | {"alembic_version"}
    chat_engine = sa.create_engine(chat_url)
    try:
        unique_constraints = sa.inspect(chat_engine).get_unique_constraints("chat_oauth_link")
        assert {constraint["name"] for constraint in unique_constraints} == {
            "uq_chat_oauth_link__github_user_id"
        }
        state_unique_constraints = sa.inspect(chat_engine).get_unique_constraints(
            "chat_oauth_state"
        )
        assert {constraint["name"] for constraint in state_unique_constraints} == {
            "uq_chat_oauth_state__actor_id"
        }
    finally:
        chat_engine.dispose()
    assert _table_names(finance_url) == finance_before

    _run_store_postgres_tests(admin_url)

    command.downgrade(chat_config, "base")
    assert _table_names(chat_url).isdisjoint(CHAT_TABLES)
    assert _table_names(finance_url) == finance_before

    admin_engine = sa.create_engine(admin_url)
    try:
        with admin_engine.connect() as connection:
            role_exists = connection.scalar(
                sa.text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :role)"),
                {"role": EXTERNAL_ROLE},
            )
            database_exists = connection.scalar(
                sa.text("SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = :database)"),
                {"database": CHAT_DATABASE},
            )
        assert role_exists is True
        assert database_exists is True
    finally:
        admin_engine.dispose()
