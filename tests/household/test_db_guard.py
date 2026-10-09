"""Safety tests for household integration database preflight."""

import pytest

from tests.household.db_guard import validate_isolated_test_database_url

_DISPOSABLE_URL = "postgresql+psycopg://fixture:synthetic@127.0.0.1:5432/penge_household_test"


def test_accepts_explicit_loopback_disposable_postgres_url() -> None:
    assert (
        validate_isolated_test_database_url(
            _DISPOSABLE_URL,
            allow_destructive_test_db="1",
        )
        == _DISPOSABLE_URL
    )


@pytest.mark.parametrize(
    ("database_url", "allow_destructive_test_db"),
    [
        (_DISPOSABLE_URL, None),
        (None, "1"),
        ("postgresql+psycopg://fixture:synthetic@example.com:5432/penge_household_test", "1"),
        ("postgresql+psycopg://fixture:synthetic@127.0.0.1:5432/penge", "1"),
        ("sqlite:///penge_household_test.db", "1"),
    ],
)
def test_rejects_non_disposable_database_configurations(
    database_url: str | None,
    allow_destructive_test_db: str | None,
) -> None:
    with pytest.raises(ValueError):
        validate_isolated_test_database_url(
            database_url,
            allow_destructive_test_db=allow_destructive_test_db,
        )
