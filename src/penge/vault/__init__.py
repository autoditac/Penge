"""Document vault — inbox watcher, OCR pipeline, hash-based filer.

Watches a Nextcloud-synced inbox directory for incoming financial PDFs
(bank statements, invoices, payslips, tax notices). Each new file is

1. hashed (SHA-256 of the byte contents) for deduplication,
2. run through Tesseract OCR (DA+DE+EN) to extract searchable text,
3. classified into a vault sub-folder (``unsorted`` until ADR-0024 +
   issue #42 ship a rules-based classifier),
4. moved to ``vault/{year}/{type}/{hash}-{slug}.{ext}`` with a sidecar
   ``.txt`` containing the OCR output.

A small heartbeat file (``vault/.health``) is written on each scan
iteration and a Prometheus-style ``/metrics`` endpoint is exposed so
Uptime Kuma (issue #52) can alert on a stalled watcher.

See ADR-0024 (``docs/decisions/0024-vault-layout.md``) for the layout
and dedup strategy rationale.
"""

from penge.vault.dedupe import HashIndex, sha256_of_file
from penge.vault.errors import VaultError
from penge.vault.filer import FilerResult, file_document
from penge.vault.health import HealthServer, Heartbeat
from penge.vault.ocr import OCRResult, extract_text
from penge.vault.watcher import VaultWatcher, WatcherConfig

__all__ = [
    "FilerResult",
    "HashIndex",
    "HealthServer",
    "Heartbeat",
    "OCRResult",
    "VaultError",
    "VaultWatcher",
    "WatcherConfig",
    "extract_text",
    "file_document",
    "sha256_of_file",
]
