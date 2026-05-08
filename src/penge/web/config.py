"""Database connection helper for the web layer.

Mirrors the resolution rules used by the ingest CLIs and by Alembic:
``DATABASE_URL`` wins, otherwise compose from ``POSTGRES_*`` vars. Kept
in its own module so unit tests can patch ``database_url`` without
importing Streamlit.
"""

from __future__ import annotations

import os

from sqlalchemy.engine import URL


def database_url() -> str:
    """Return the SQLAlchemy URL for the Penge Postgres instance.

    Checks ``DATABASE_URL`` first; falls back to assembling a URL from
    ``POSTGRES_USER`` / ``POSTGRES_PASSWORD`` / ``POSTGRES_HOST`` /
    ``POSTGRES_PORT`` / ``POSTGRES_DB`` (same defaults as
    ``compose.yaml``). Uses :meth:`sqlalchemy.engine.URL.create` so
    reserved characters in the username or password are escaped
    correctly.
    """
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    rendered = URL.create(
        drivername="postgresql+psycopg",
        username=os.environ.get("POSTGRES_USER", "penge"),
        password=os.environ.get("POSTGRES_PASSWORD") or None,
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        database=os.environ.get("POSTGRES_DB", "penge"),
    ).render_as_string(hide_password=False)
    return str(rendered)
