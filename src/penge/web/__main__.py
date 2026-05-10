"""CLI shim that launches ``streamlit run`` against ``app.py``.

Lets users start the dashboard with ``penge-web`` (matching the
``penge-ecb-fx`` and ``penge-nordnet`` commands) without remembering
the full streamlit invocation. Extra arguments are forwarded verbatim
so flags like ``--server.port`` keep working::

    penge-web --server.port 8765 --server.address 100.64.0.1
"""

from __future__ import annotations

import sys
from pathlib import Path

# Resolve once at import time so the path is stable regardless of cwd.
APP_PATH = Path(__file__).resolve().parent / "app.py"


def main(argv: list[str] | None = None) -> int:
    """Forward to ``streamlit.web.cli.main`` with ``run <app>`` prepended."""
    args = list(sys.argv[1:] if argv is None else argv)

    # Lazy import: keeps ``--help`` discoverable even if streamlit is
    # missing (the import error then surfaces with a useful message).
    try:
        from streamlit.web import cli as stcli
    except ImportError as exc:  # pragma: no cover — bootstrap-only path
        sys.stderr.write(
            "streamlit is not installed. Install the web group: `uv sync --group web --group db`.\n"
        )
        raise SystemExit(2) from exc

    sys.argv = ["streamlit", "run", str(APP_PATH), *args]
    return int(stcli.main() or 0)


if __name__ == "__main__":
    sys.exit(main())
