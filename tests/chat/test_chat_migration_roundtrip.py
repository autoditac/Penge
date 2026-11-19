"""Integration coverage for the dedicated chat OAuth Alembic chain."""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

ADMIN_URL_ENV = "PENGE_CHAT_MIGRATION_TEST_ADMIN_URL"
CHAT_TABLES = {"chat_oauth_link", "chat_oauth_state", "chat_audit_event"}


def _synthetic_password(suffix: str) -> str:
    return f"synthetic@{suffix}"


EXTERNAL_ROLE_PASSWORD = _synthetic_password("migration")
STORE_ROLE_PASSWORD = _synthetic_password("store")


@dataclass(frozen=True)
class IsolatedResources:
    """Per-run PostgreSQL names; a unique suffix avoids touching pre-existing resources."""

    finance_database: str
    chat_database: str
    external_role: str
    store_role: str

    @classmethod
    def unique(cls) -> IsolatedResources:
        suffix = uuid.uuid4().hex[:16]
        return cls(
            finance_database=f"penge_finance_migration_test_{suffix}",
            chat_database=f"penge_chat_oauth_migration_test_{suffix}",
            external_role=f"penge_chat_oauth_migration_test_{suffix}",
            store_role=f"penge_chat_oauth_store_test_{suffix}",
        )


@dataclass(frozen=True)
class IsolatedDatabases:
    finance_url: str
    chat_url: str
    admin_url: str
    resources: IsolatedResources


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
def isolated_databases() -> Iterator[IsolatedDatabases]:
    """Create uniquely named finance/chat databases and roles, dropping only those created here."""
    admin_url = os.environ.get(ADMIN_URL_ENV)
    if admin_url is None:
        pytest.skip(f"{ADMIN_URL_ENV} is required for the migration integration test")
    resources = IsolatedResources.unique()
    created_roles: list[str] = []
    created_databases: list[str] = []
    engine = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            # CREATE fails if a same-named resource exists; nothing pre-existing is dropped.
            connection.execute(
                sa.text(
                    f"""CREATE ROLE "{resources.external_role}" LOGIN
                    PASSWORD '{EXTERNAL_ROLE_PASSWORD}'"""
                )
            )
            created_roles.append(resources.external_role)
            connection.execute(
                sa.text(
                    f"CREATE ROLE \"{resources.store_role}\" LOGIN PASSWORD '{STORE_ROLE_PASSWORD}'"
                )
            )
            created_roles.append(resources.store_role)
            connection.execute(sa.text(f'CREATE DATABASE "{resources.finance_database}"'))
            created_databases.append(resources.finance_database)
            connection.execute(
                sa.text(
                    f'CREATE DATABASE "{resources.chat_database}" OWNER "{resources.external_role}"'
                )
            )
            created_databases.append(resources.chat_database)
        yield IsolatedDatabases(
            finance_url=_database_url(admin_url, resources.finance_database),
            chat_url=_database_url(
                admin_url,
                resources.chat_database,
                username=resources.external_role,
                password=EXTERNAL_ROLE_PASSWORD,
            ),
            admin_url=admin_url,
            resources=resources,
        )
    finally:
        with engine.connect() as connection:
            for database in reversed(created_databases):
                connection.execute(sa.text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
            for role in reversed(created_roles):
                connection.execute(sa.text(f'DROP ROLE IF EXISTS "{role}"'))
        engine.dispose()


def _table_names(database_url: str) -> set[str]:
    engine = sa.create_engine(database_url)
    try:
        return set(sa.inspect(engine).get_table_names(schema="public"))
    finally:
        engine.dispose()


def _run_store_vitest(env: dict[str, str]) -> None:
    pnpm = shutil.which("pnpm")
    assert pnpm is not None
    result = subprocess.run(  # noqa: S603 - resolved executable, constant arguments
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
        env={**os.environ, **env},
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert " passed" in result.stdout, result.stdout + result.stderr


def _run_store_postgres_tests(admin_url: str, resources: IsolatedResources) -> None:
    store_role = resources.store_role
    chat_admin_url = _database_url(admin_url, resources.chat_database)
    chat_admin_engine = sa.create_engine(chat_admin_url)
    store_url = _database_url(
        admin_url,
        resources.chat_database,
        username=store_role,
        password=STORE_ROLE_PASSWORD,
    )
    rejection_env = {
        "PENGE_CHAT_STORE_TEST_DATABASE_URL": store_url,
        "PENGE_CHAT_STORE_TEST_ROLE": store_role,
        "PENGE_CHAT_STORE_EXPECT_PRIVILEGE_REJECTION": "1",
    }
    try:
        with chat_admin_engine.begin() as connection:
            connection.execute(
                sa.text("CREATE TABLE finance_shadow (id integer PRIMARY KEY, amount numeric)")
            )
            connection.execute(sa.text(f'GRANT USAGE ON SCHEMA public TO "{store_role}"'))
            connection.execute(
                sa.text(
                    f"GRANT SELECT, INSERT, UPDATE, DELETE ON "
                    f'chat_oauth_link, chat_oauth_state TO "{store_role}"'
                )
            )
            connection.execute(sa.text(f'GRANT INSERT ON chat_audit_event TO "{store_role}"'))
            connection.execute(
                sa.text(
                    f'GRANT USAGE, SELECT ON SEQUENCE chat_audit_event_id_seq TO "{store_role}"'
                )
            )
            connection.execute(
                sa.text(f'GRANT SELECT (amount) ON finance_shadow TO "{store_role}"')
            )
        _run_store_vitest(
            {
                **rejection_env,
                "PENGE_CHAT_STORE_EXPECT_REJECTED_RELATION": "public.finance_shadow",
            }
        )
        with chat_admin_engine.begin() as connection:
            connection.execute(sa.text("DROP TABLE finance_shadow"))
            connection.execute(sa.text("CREATE SCHEMA finance_marts"))
            connection.execute(
                sa.text(
                    "CREATE MATERIALIZED VIEW finance_marts.net_worth_shadow AS "
                    "SELECT 1::integer AS id, 100::numeric AS amount"
                )
            )
            connection.execute(sa.text(f'GRANT USAGE ON SCHEMA finance_marts TO "{store_role}"'))
            connection.execute(
                sa.text(f'GRANT SELECT ON finance_marts.net_worth_shadow TO "{store_role}"')
            )
        _run_store_vitest(
            {
                **rejection_env,
                "PENGE_CHAT_STORE_EXPECT_REJECTED_RELATION": "finance_marts.net_worth_shadow",
            }
        )
        with chat_admin_engine.begin() as connection:
            connection.execute(sa.text("DROP SCHEMA finance_marts CASCADE"))
        _run_store_vitest(
            {
                "PENGE_CHAT_STORE_TEST_DATABASE_URL": store_url,
                "PENGE_CHAT_STORE_TEST_ADMIN_URL": chat_admin_url,
                "PENGE_CHAT_STORE_TEST_ROLE": store_role,
            }
        )
    finally:
        chat_admin_engine.dispose()


def test_dedicated_chat_migration_roundtrip(
    isolated_databases: IsolatedDatabases,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Round-trip chat storage without touching finance schema or role lifecycle."""
    finance_url = isolated_databases.finance_url
    chat_url = isolated_databases.chat_url
    admin_url = isolated_databases.admin_url
    resources = isolated_databases.resources
    assert "%40" in chat_url
    finance_config = Config("alembic.ini")
    monkeypatch.setenv("DATABASE_URL", finance_url)
    command.upgrade(finance_config, "head")
    finance_before = _table_names(finance_url)
    assert finance_before
    assert finance_before.isdisjoint(CHAT_TABLES)

    secret_path = tmp_path / "chat-database-url"
    bare_chat_url = chat_url.replace("postgresql+psycopg://", "postgresql://", 1)
    assert bare_chat_url.startswith("postgresql://")
    assert "%40" in bare_chat_url
    secret_path.write_text(bare_chat_url, encoding="utf-8")
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

    _run_store_postgres_tests(admin_url, resources)

    command.downgrade(chat_config, "base")
    assert _table_names(chat_url).isdisjoint(CHAT_TABLES)
    assert _table_names(finance_url) == finance_before

    admin_engine = sa.create_engine(admin_url)
    try:
        with admin_engine.connect() as connection:
            role_exists = connection.scalar(
                sa.text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :role)"),
                {"role": resources.external_role},
            )
            database_exists = connection.scalar(
                sa.text("SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = :database)"),
                {"database": resources.chat_database},
            )
        assert role_exists is True
        assert database_exists is True
    finally:
        admin_engine.dispose()
