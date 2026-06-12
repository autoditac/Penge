"""Environment-driven settings for the import-session surface.

All knobs are read lazily so importing the module has no side
effects and tests can monkeypatch the environment per case.
"""

from __future__ import annotations

import os
import shlex
from pathlib import Path

#: Hard cap for one uploaded statement. Real exports are well under
#: 5 MiB; 25 MiB leaves headroom for scanned PDFs without letting a
#: stray upload fill the disk.
DEFAULT_MAX_UPLOAD_BYTES = 25 * 1024 * 1024

#: Sessions are working state, not an archive; a week is enough to
#: finish a review while keeping the staging table bounded.
DEFAULT_SESSION_TTL_DAYS = 7

#: Uploads live under the gitignored ``data/`` tree by default.
DEFAULT_IMPORT_DIR = "data/imports"


def import_dir() -> Path:
    """Directory under which uploaded session files are stored."""
    return Path(os.environ.get("PENGE_IMPORT_DIR", DEFAULT_IMPORT_DIR))


def max_upload_bytes() -> int:
    """Upload size cap in bytes (HTTP 413 above this)."""
    raw = os.environ.get("PENGE_IMPORT_MAX_BYTES")
    if raw is None:
        return DEFAULT_MAX_UPLOAD_BYTES
    value = int(raw)
    if value <= 0:
        raise ValueError(f"PENGE_IMPORT_MAX_BYTES must be positive, got {value}")
    return value


def session_ttl_days() -> int:
    """Days a staged session stays usable before lazy expiry."""
    raw = os.environ.get("PENGE_IMPORT_SESSION_TTL_DAYS")
    if raw is None:
        return DEFAULT_SESSION_TTL_DAYS
    value = int(raw)
    if value <= 0:
        raise ValueError(f"PENGE_IMPORT_SESSION_TTL_DAYS must be positive, got {value}")
    return value


def nordnet_accounts_config_path() -> Path | None:
    """Path to the Nordnet accounts YAML (required to commit Nordnet files).

    The mapping from Nordnet kontonummer to entity/kind is operator
    config, not upload data, so it comes from the environment — the
    same file the ``penge-nordnet`` CLI takes via ``--accounts-config``.
    """
    raw = os.environ.get("PENGE_NORDNET_ACCOUNTS_CONFIG")
    return Path(raw) if raw else None


def mcp_suggest_command() -> list[str] | None:
    """Command line that launches the MCP server for mapping suggestions.

    Unset (or blank) means the AI review layer is disabled and the
    suggestions endpoint answers 503. Typical value:
    ``node apps/mcp/dist/index.js``.
    """
    raw = os.environ.get("PENGE_MCP_SUGGEST_COMMAND")
    if raw is None or not raw.strip():
        return None
    return shlex.split(raw)


#: Suggestion calls spawn a fresh MCP server process; 30 s covers
#: Node start-up plus the read-only queries with margin.
DEFAULT_MCP_SUGGEST_TIMEOUT_SECONDS = 30.0


def mcp_suggest_timeout_seconds() -> float:
    """Wall-clock budget for one MCP suggestion call."""
    raw = os.environ.get("PENGE_MCP_SUGGEST_TIMEOUT_SECONDS")
    if raw is None:
        return DEFAULT_MCP_SUGGEST_TIMEOUT_SECONDS
    value = float(raw)
    if value <= 0:
        raise ValueError(f"PENGE_MCP_SUGGEST_TIMEOUT_SECONDS must be positive, got {value}")
    return value
