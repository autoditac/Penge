"""Filesystem watcher that drives the vault OCR + filer pipeline.

Architecture::

    inbox/  --watchdog-->  queue  --worker thread-->  ocr -> filer -> vault/
                                                       |
                                                       +-> heartbeat + metrics

* The watchdog observer enqueues paths only — never touches the file —
  so a slow scan/copy from Nextcloud cannot race the OCR step. The
  worker thread waits for ``stable_for`` seconds of unchanged size + mtime
  before processing.
* A periodic *scan tick* re-walks the inbox so files that landed while
  the watcher was offline are not lost. The tick also writes the
  heartbeat used by Uptime Kuma (issue #52).
* Exceptions in the worker are logged and counted but never crash the
  watcher; one bad PDF should not stop the rest of the inbox.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from penge.vault.classifier import (
    UNSORTED_CATEGORY,
    Classification,
    ClassifierConfig,
    classify,
)
from penge.vault.classifier import (
    load_config as load_classifier_config,
)
from penge.vault.dedupe import HashIndex
from penge.vault.errors import VaultError
from penge.vault.filer import UNSORTED_TYPE, FilerResult, file_document
from penge.vault.health import HealthServer, Heartbeat
from penge.vault.ocr import OCRConfig, extract_text

log = logging.getLogger("penge.vault.watcher")

#: Files we attempt to OCR and file. Anything else is left in the inbox
#: with a warning so a human can decide what to do.
SUPPORTED_SUFFIXES: frozenset[str] = frozenset({".pdf"})

#: Sentinel pushed onto the work queue to wake the worker for shutdown.
_SHUTDOWN = object()


class WatcherConfig(BaseModel):
    """User-facing configuration for the vault watcher."""

    inbox: Path = Field(description="Directory to watch for incoming documents.")
    vault_root: Path = Field(description="Root of the on-disk vault tree.")
    ocr: OCRConfig = Field(default_factory=OCRConfig)
    scan_interval_s: float = Field(default=5.0, gt=0, description="Periodic re-scan interval.")
    stable_for_s: float = Field(
        default=2.0,
        ge=0,
        description="Wait this long after the last size/mtime change before processing.",
    )
    health_host: str = Field(default="127.0.0.1")
    health_port: int = Field(default=0, ge=0, le=65535)
    classifier_config_path: Path | None = Field(
        default=None,
        description=(
            "Optional path to a custom classifier YAML. If ``None``, the rules "
            "bundled with the package (``penge.vault.classifier_rules.yaml``) "
            "are used; this works both from a source checkout and from an "
            "installed wheel. Override via the ``--classifier-config`` CLI flag."
        ),
    )


@dataclass
class _Metrics:
    """Mutable counters surfaced through the metrics endpoint."""

    files_seen: int = 0
    files_filed: int = 0
    duplicates: int = 0
    failures: int = 0
    unclassified: int = 0
    last_scan_iso: str = ""
    started_at: float = field(default_factory=time.time)
    index_len: Callable[[], int] = field(default=lambda: 0)

    def snapshot(self) -> dict[str, float]:
        return {
            "vault_up": 1.0,
            "vault_uptime_seconds": time.time() - self.started_at,
            "vault_files_seen_total": float(self.files_seen),
            "vault_files_filed_total": float(self.files_filed),
            "vault_duplicates_total": float(self.duplicates),
            "vault_failures_total": float(self.failures),
            "vault_unclassified_total": float(self.unclassified),
            "vault_index_size": float(self.index_len()),
        }


class _InboxEventHandler(FileSystemEventHandler):
    """Forward newly-created files into the worker queue."""

    def __init__(self, work: queue.Queue[Path | object]) -> None:
        self._work = work

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        path_attr = event.src_path
        path_str = path_attr.decode() if isinstance(path_attr, bytes) else str(path_attr)
        self._work.put(Path(path_str))

    def on_moved(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        dest_attr = getattr(event, "dest_path", "")
        dest_str = dest_attr.decode() if isinstance(dest_attr, bytes) else str(dest_attr)
        if dest_str:
            self._work.put(Path(dest_str))


class VaultWatcher:
    """Coordinates the watchdog observer, work queue, OCR + filer.

    Use :meth:`start` to launch background threads (observer, worker,
    scan ticker, health server) and :meth:`stop` for an orderly
    shutdown. :meth:`run_forever` blocks the caller and stops on
    KeyboardInterrupt.
    """

    def __init__(
        self,
        config: WatcherConfig,
        *,
        observer_factory: Callable[[], BaseObserver] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._clock = clock or (lambda: datetime.now(UTC))
        self._work: queue.Queue[Path | object] = queue.Queue()
        self._stop_event = threading.Event()

        config.vault_root.mkdir(parents=True, exist_ok=True)
        config.inbox.mkdir(parents=True, exist_ok=True)

        self._index = HashIndex(config.vault_root / ".index.json")
        self._heartbeat = Heartbeat(config.vault_root)
        self._metrics = _Metrics(index_len=lambda: len(self._index))
        self._classifier: ClassifierConfig = load_classifier_config(config.classifier_config_path)

        self._observer: BaseObserver = (observer_factory or Observer)()
        self._observer.schedule(
            _InboxEventHandler(self._work),
            str(config.inbox),
            recursive=False,
        )

        self._health = HealthServer(
            heartbeat=self._heartbeat,
            metrics_source=self,
            host=config.health_host,
            port=config.health_port,
        )

        self._worker = threading.Thread(target=self._run_worker, name="vault-worker")
        self._ticker = threading.Thread(target=self._run_ticker, name="vault-ticker")

    # -- public surface --------------------------------------------------

    @property
    def index(self) -> HashIndex:
        return self._index

    @property
    def heartbeat(self) -> Heartbeat:
        return self._heartbeat

    @property
    def health_port(self) -> int:
        return self._health.port

    def metrics(self) -> dict[str, float]:
        """Snapshot of current counters — consumed by the health server."""

        return self._metrics.snapshot()

    def start(self) -> None:
        log.info(
            "vault.watcher.starting inbox=%s vault_root=%s",
            self._config.inbox,
            self._config.vault_root,
        )
        self._heartbeat.beat(self._clock())
        self._observer.start()
        self._health.start()
        self._worker.start()
        self._ticker.start()

    def stop(self) -> None:
        log.info("vault.watcher.stopping")
        self._stop_event.set()
        self._work.put(_SHUTDOWN)
        try:
            self._observer.stop()
            self._observer.join(timeout=5)
        except RuntimeError:
            pass
        self._worker.join(timeout=10)
        self._ticker.join(timeout=10)
        self._health.stop()

    def run_forever(self) -> None:
        self.start()
        try:
            while not self._stop_event.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            log.info("vault.watcher.interrupt")
        finally:
            self.stop()

    def process_inbox_once(self) -> list[FilerResult]:
        """Process every supported file currently in the inbox.

        Mainly intended for tests and the ``--once`` CLI flag.
        """

        results: list[FilerResult] = []
        for path in sorted(self._config.inbox.iterdir()):
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            result = self._handle_path(path)
            if result is not None:
                results.append(result)
        self._heartbeat.beat(self._clock())
        self._metrics.last_scan_iso = self._clock().isoformat()
        return results

    # -- internals -------------------------------------------------------

    def _run_worker(self) -> None:
        while True:
            item = self._work.get()
            if item is _SHUTDOWN:
                return
            assert isinstance(item, Path)  # noqa: S101 - private invariant; only Path|sentinel is enqueued
            if self._stop_event.is_set():
                return
            try:
                self._wait_until_stable(item)
                self._handle_path(item)
            except Exception:
                self._metrics.failures += 1
                log.exception("vault.worker.error path=%s", item)

    def _run_ticker(self) -> None:
        while not self._stop_event.wait(self._config.scan_interval_s):
            try:
                for path in self._config.inbox.iterdir():
                    if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
                        self._work.put(path)
                self._heartbeat.beat(self._clock())
                self._metrics.last_scan_iso = self._clock().isoformat()
            except Exception:
                self._metrics.failures += 1
                log.exception("vault.ticker.error")

    def _wait_until_stable(self, path: Path) -> None:
        """Block until *path*'s size + mtime stop changing."""

        deadline_idle = self._config.stable_for_s
        last: tuple[int, float] | None = None
        idle_start: float | None = None
        while not self._stop_event.is_set():
            if not path.exists():
                return
            try:
                stat = path.stat()
            except FileNotFoundError:
                return
            current = (stat.st_size, stat.st_mtime)
            if current == last:
                if idle_start is None:
                    idle_start = time.monotonic()
                if time.monotonic() - idle_start >= deadline_idle:
                    return
            else:
                idle_start = None
                last = current
            time.sleep(min(0.25, deadline_idle / 4 + 0.05))

    def _handle_path(self, path: Path) -> FilerResult | None:
        if not path.exists() or not path.is_file():
            return None
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            log.warning("vault.worker.unsupported path=%s", path)
            return None
        self._metrics.files_seen += 1
        try:
            ocr = extract_text(path, self._config.ocr)
        except VaultError:
            self._metrics.failures += 1
            log.exception("vault.worker.ocr_failed path=%s", path)
            return None
        classification: Classification = classify(ocr.text, config=self._classifier)
        document_type = classification.category
        if document_type == UNSORTED_CATEGORY:
            document_type = UNSORTED_TYPE
            self._metrics.unclassified += 1
            log.warning(
                "vault.classifier.unclassified path=%s confidence=%.2f matched_rules=%s",
                path,
                classification.confidence,
                list(classification.matched_rules),
            )
        else:
            log.info(
                "vault.classifier.matched path=%s category=%s confidence=%.2f",
                path,
                classification.category,
                classification.confidence,
            )
        result = file_document(
            path,
            vault_root=self._config.vault_root,
            index=self._index,
            ocr_text=ocr.text,
            document_type=document_type,
            now=self._clock(),
        )
        if result.duplicate:
            self._metrics.duplicates += 1
        else:
            self._metrics.files_filed += 1
        return result
