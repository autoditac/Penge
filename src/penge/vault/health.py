"""Heartbeat file + Prometheus-style HTTP endpoint for the vault.

Two health surfaces:

* :class:`Heartbeat` — a tiny on-disk file at ``<vault_root>/.health``
  whose mtime is bumped on every watcher iteration. A monitor (e.g.
  Uptime Kuma's "Push" type, or a cron + ``find -mmin``) can alert if
  the file goes stale.
* :class:`HealthServer` — a stdlib ``http.server`` exposing two routes:
    ``GET /health``   →  ``200 OK`` with the heartbeat timestamp.
    ``GET /metrics``  →  Prometheus text-format metrics (``vault_*``).

Stdlib was chosen over aiohttp/uvicorn because the surface is two
endpoints with no auth and no application logic, and the no-new-deps
rule from ``AGENTS.md`` applies. See ADR-0024 for the rationale.
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Protocol

log = logging.getLogger("penge.vault.health")

HEARTBEAT_FILENAME = ".health"


class _MetricsSource(Protocol):
    """Minimal interface the metrics endpoint queries on each request."""

    def metrics(self) -> dict[str, float]: ...


class Heartbeat:
    """A small file whose mtime represents the watcher's liveness."""

    def __init__(self, vault_root: Path) -> None:
        self._path = vault_root / HEARTBEAT_FILENAME
        self._last: datetime | None = None
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def last(self) -> datetime | None:
        with self._lock:
            return self._last

    def beat(self, now: datetime | None = None) -> datetime:
        """Update the on-disk heartbeat to *now* (UTC by default)."""

        timestamp = now or datetime.now(UTC)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(timestamp.isoformat() + "\n", encoding="utf-8")
        with self._lock:
            self._last = timestamp
        return timestamp


class _Handler(BaseHTTPRequestHandler):
    server_version = "PengeVault/0.1"

    def log_message(self, format: str, *args: object) -> None:
        log.debug("vault.health.access " + format, *args)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._handle_health()
        elif self.path == "/metrics":
            self._handle_metrics()
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "unknown route")

    def _handle_health(self) -> None:
        heartbeat: Heartbeat = self.server.heartbeat  # type: ignore[attr-defined]  # set in HealthServer
        last = heartbeat.last
        if last is None:
            body = b"starting\n"
            status = HTTPStatus.SERVICE_UNAVAILABLE
        else:
            body = (last.isoformat() + "\n").encode("utf-8")
            status = HTTPStatus.OK
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_metrics(self) -> None:
        source: _MetricsSource = self.server.metrics_source  # type: ignore[attr-defined]  # set in HealthServer
        lines: list[str] = []
        for key, value in source.metrics().items():
            lines.append(f"# TYPE {key} gauge")
            lines.append(f"{key} {value}")
        body = ("\n".join(lines) + "\n").encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class HealthServer:
    """Background HTTP server exposing ``/health`` and ``/metrics``."""

    def __init__(
        self,
        *,
        heartbeat: Heartbeat,
        metrics_source: _MetricsSource,
        host: str = "127.0.0.1",
        port: int = 0,
    ) -> None:
        self._heartbeat = heartbeat
        self._metrics_source = metrics_source
        self._server = ThreadingHTTPServer((host, port), _Handler)
        self._server.heartbeat = heartbeat  # type: ignore[attr-defined]  # extension attr for handler
        self._server.metrics_source = metrics_source  # type: ignore[attr-defined]  # extension attr for handler
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    @property
    def host(self) -> str:
        return str(self._server.server_address[0])

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="penge-vault-health",
            daemon=True,
        )
        self._thread.start()
        log.info("vault.health.started host=%s port=%s", self.host, self.port)

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        log.info("vault.health.stopped")
