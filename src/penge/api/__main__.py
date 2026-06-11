"""CLI entrypoint: run the read API under uvicorn.

Binds to 127.0.0.1 by default — the API serves the local WebUI only.
Set ``PENGE_API_HOST`` / ``PENGE_API_PORT`` to override (e.g. in the
container image, where it must bind 0.0.0.0).
"""

from __future__ import annotations

import argparse
import os

import uvicorn


def main() -> None:
    """Parse arguments and serve :func:`penge.api.app.create_app`."""
    parser = argparse.ArgumentParser(description="Serve the Penge read API.")
    parser.add_argument(
        "--host",
        default=os.environ.get("PENGE_API_HOST", "127.0.0.1"),
        help="Bind address (default: 127.0.0.1 or $PENGE_API_HOST).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PENGE_API_PORT", "8000")),
        help="Bind port (default: 8000 or $PENGE_API_PORT).",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload (development only).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Log at DEBUG level instead of INFO.",
    )
    args = parser.parse_args()

    uvicorn.run(
        "penge.api.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        # Passed straight to uvicorn so --verbose deterministically switches
        # its loggers to DEBUG (uvicorn configures logging itself; a
        # logging.basicConfig call here would not reliably apply).
        log_level="debug" if args.verbose else "info",
    )


if __name__ == "__main__":
    main()
