"""Content-hash deduplication for the vault.

The vault filer keys every stored document by the SHA-256 of its raw
byte content. A small sidecar JSON index at ``<vault_root>/.index.json``
maps each known hash to its filed path so the watcher can answer
"have I seen this file before?" in O(1) without rescanning the tree.

The index is intentionally a flat JSON file — not Postgres — so the
vault remains *self-contained on disk*: a Nextcloud sync of the vault
directory is always sufficient to reconstruct state on a new host.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from pathlib import Path
from typing import TypedDict

log = logging.getLogger("penge.vault.dedupe")

CHUNK_SIZE = 1024 * 1024


class IndexEntry(TypedDict):
    """One row in the on-disk hash index."""

    path: str
    size: int
    filed_at: str


def sha256_of_file(path: Path) -> str:
    """Return the lowercase hex SHA-256 of the bytes at *path*.

    Streamed in 1 MiB chunks so multi-hundred-MB scanned PDFs do not
    pin memory.
    """

    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


class HashIndex:
    """Sidecar JSON index of ``sha256 -> IndexEntry`` for the vault.

    Thread-safe: ``add`` and ``contains`` may be called from the
    watcher's worker thread while the health server's metrics endpoint
    reads ``__len__`` from another thread.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._entries: dict[str, IndexEntry] = {}
        self._load()

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            log.warning("vault.index.unreadable path=%s", self._path)
            return
        if not isinstance(raw, dict):
            log.warning("vault.index.malformed path=%s", self._path)
            return
        for key, value in raw.items():
            if (
                isinstance(key, str)
                and isinstance(value, dict)
                and "path" in value
                and "size" in value
                and "filed_at" in value
            ):
                self._entries[key] = IndexEntry(
                    path=str(value["path"]),
                    size=int(value["size"]),
                    filed_at=str(value["filed_at"]),
                )

    def _flush(self) -> None:
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(self._entries, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self._path)

    def contains(self, sha256: str) -> bool:
        with self._lock:
            return sha256 in self._entries

    def get(self, sha256: str) -> IndexEntry | None:
        with self._lock:
            return self._entries.get(sha256)

    def add(self, sha256: str, entry: IndexEntry) -> None:
        with self._lock:
            self._entries[sha256] = entry
            self._flush()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)
