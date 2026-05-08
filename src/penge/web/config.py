"""Database connection helper for the web layer.

Mirrors the resolution rules used by the ingest CLIs and by Alembic:
``DATABASE_URL`` wins, otherwise compose from ``POSTGRES_*`` vars. Kept
in its own module so unit tests can patch ``database_url`` without
importing Streamlit.
"""

from __future__ import annotations

import os


def database_url() -> str:
    """Return the SQLAlchemy URL for the Penge Postgres instance.

    Checks ``DATABASE_URL`` first; falls back to assembling a URL from
    ``POSTGRES_USER`` / ``POSTGRES_PASSWORD`` / ``POSTGRES_HOST`` /
    ``POSTGRES_PORT`` / ``POSTGRES_DB`` (same defaults as
    ``compose.yaml``).
    """
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    user = os.environ.get("POSTGRES_USER", "penge")
    password = os.environ.get("POSTGRES_PASSWORD", "")
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "penge")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db}"
