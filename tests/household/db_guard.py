"""Safety checks for the destructive household integration test database."""

from sqlalchemy.engine import make_url


def validate_isolated_test_database_url(
    database_url: str | None,
    *,
    allow_destructive_test_db: str | None,
) -> str:
    """Require explicit opt-in and a loopback Postgres database named for tests."""
    if allow_destructive_test_db != "1":
        raise ValueError("Set PENGE_ALLOW_DESTRUCTIVE_TEST_DB=1 only for a disposable test DB")
    if database_url is None or database_url == "":
        raise ValueError("PENGE_TEST_DATABASE_URL is required")

    parsed = make_url(database_url)
    if parsed.drivername not in {"postgresql", "postgresql+psycopg"}:
        raise ValueError("Household integration tests require PostgreSQL")
    if parsed.host not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Household integration tests require a loopback database host")
    database_name = parsed.database or ""
    if not database_name.lower().endswith(("test", "_test", "_tests")):
        raise ValueError("Household integration tests require a database name ending in test")

    return database_url
