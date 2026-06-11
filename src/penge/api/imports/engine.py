"""Write-enabled engine for the import-session surface.

ADR-0035 made the read API's engine open every transaction READ
ONLY. Staged imports are the one sanctioned write path in the API
process (ADR-0037), so they get their own engine — created lazily,
cached, and used nowhere else.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from penge.web.config import database_url

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine


@lru_cache(maxsize=1)
def get_import_engine() -> Engine:
    """Return the write-enabled engine for import sessions."""
    # Lazy import mirrors penge.api.data.get_engine: importing this
    # module must not require the DB driver.
    from sqlalchemy import create_engine

    return create_engine(database_url(), pool_pre_ping=True)
