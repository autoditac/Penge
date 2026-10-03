"""Seed only the explicitly opted-in disposable CI database for real browser tests."""

from __future__ import annotations

import os

from sqlalchemy import create_engine

from tests.household.browser_fixtures import seed_browser_journeys
from tests.household.db_guard import validate_isolated_test_database_url
from tests.household.fixtures import seed_household_source_facts


def main() -> None:
    """Use the same synthetic bank fixture as the database acceptance suite."""
    url = validate_isolated_test_database_url(
        os.environ.get("PENGE_TEST_DATABASE_URL"),
        allow_destructive_test_db=os.environ.get("PENGE_ALLOW_DESTRUCTIVE_TEST_DB"),
    )
    engine = create_engine(url)
    try:
        seeded = seed_household_source_facts(engine)
        seed_browser_journeys(engine, seeded.account_ids["eur-checking"])
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
