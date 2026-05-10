"""Integration tests for :class:`penge.vault.watcher.VaultWatcher`."""

from __future__ import annotations

import shutil
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path

import pytest

from penge.vault.ocr import OCRConfig
from penge.vault.watcher import VaultWatcher, WatcherConfig

FIXTURES = Path(__file__).parent / "fixtures"


def _make_config(tmp_path: Path) -> WatcherConfig:
    return WatcherConfig(
        inbox=tmp_path / "inbox",
        vault_root=tmp_path / "vault",
        ocr=OCRConfig(langs="eng", dpi=150),
        scan_interval_s=0.5,
        stable_for_s=0.0,
        health_host="127.0.0.1",
        health_port=0,
    )


def _wait_for(predicate: Callable[[], bool], timeout: float = 60.0, interval: float = 0.2) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_dropped_file_is_filed_within_60s(tmp_path: Path) -> None:
    """DoD: PDF dropped → OCR'd → filed at vault/{year}/unsorted/<hash>-*.pdf within 60s."""

    config = _make_config(tmp_path)
    watcher = VaultWatcher(config)
    watcher.start()
    try:
        shutil.copy(FIXTURES / "sample_en.pdf", config.inbox / "drop.pdf")

        def filed() -> bool:
            return any(config.vault_root.rglob("*.pdf"))

        assert _wait_for(filed, timeout=60.0)

        pdfs = list(config.vault_root.rglob("*.pdf"))
        assert len(pdfs) == 1
        # vault/<year>/unsorted/<sha256>-<slug>.pdf
        relative = pdfs[0].relative_to(config.vault_root)
        parts = relative.parts
        assert len(parts) == 3
        assert parts[0].isdigit() and len(parts[0]) == 4  # year
        assert parts[1] == "unsorted"
        sha_prefix = parts[2].split("-", 1)[0]
        assert len(sha_prefix) == 64
        # OCR sidecar exists with non-empty content (embedded text).
        sidecar = pdfs[0].with_suffix(".txt")
        assert sidecar.is_file()
        assert "Statement" in sidecar.read_text(encoding="utf-8")
    finally:
        watcher.stop()


def test_duplicate_drop_is_deduped(tmp_path: Path) -> None:
    """DoD: drop the same file twice → only one copy in the vault."""

    config = _make_config(tmp_path)
    watcher = VaultWatcher(config)
    watcher.start()
    try:
        shutil.copy(FIXTURES / "sample_en.pdf", config.inbox / "first.pdf")
        assert _wait_for(lambda: any(config.vault_root.rglob("*.pdf")), timeout=60.0)

        shutil.copy(FIXTURES / "sample_en.pdf", config.inbox / "second.pdf")

        # Wait for the duplicates counter to tick (or 30s timeout).
        def deduped() -> bool:
            return watcher.metrics()["vault_duplicates_total"] >= 1.0

        assert _wait_for(deduped, timeout=30.0)
        # Inbox is empty (duplicate removed), vault still has exactly one PDF.
        assert not list(config.inbox.iterdir())
        pdfs = list(config.vault_root.rglob("*.pdf"))
        assert len(pdfs) == 1
    finally:
        watcher.stop()


def test_health_endpoint_reports_status(tmp_path: Path) -> None:
    """DoD: /metrics endpoint returns Prometheus text and /health returns OK."""

    config = _make_config(tmp_path)
    watcher = VaultWatcher(config)
    watcher.start()
    try:
        port = watcher.health_port
        assert port > 0

        # /health responds with a heartbeat timestamp once started.
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as resp:
            assert resp.status == 200
            body = resp.read().decode("utf-8").strip()
            # Expect an ISO-8601 timestamp.
            assert "T" in body and ("+" in body or "Z" in body)

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=5) as resp:
            assert resp.status == 200
            body = resp.read().decode("utf-8")
            assert "vault_up 1.0" in body
            assert "vault_files_seen_total" in body

        assert watcher.heartbeat.path.is_file()
    finally:
        watcher.stop()


def test_process_inbox_once_drains_and_writes_heartbeat(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    watcher = VaultWatcher(config)
    # Don't start background threads — exercise the synchronous path.
    shutil.copy(FIXTURES / "sample_dk.pdf", config.inbox / "dk.pdf")
    shutil.copy(FIXTURES / "sample_de.pdf", config.inbox / "de.pdf")

    results = watcher.process_inbox_once()
    assert len(results) == 2
    assert all(not r.duplicate for r in results)
    assert watcher.heartbeat.path.is_file()
    pdfs = list(config.vault_root.rglob("*.pdf"))
    assert len(pdfs) == 2


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract binary not installed")
def test_real_tesseract_does_not_crash_pipeline(tmp_path: Path) -> None:
    """If Tesseract is installed but pdfplumber returns text, the embedded path wins."""

    config = _make_config(tmp_path)
    watcher = VaultWatcher(config)
    shutil.copy(FIXTURES / "sample_en.pdf", config.inbox / "drop.pdf")
    results = watcher.process_inbox_once()
    assert len(results) == 1
    assert results[0].filed_path is not None
