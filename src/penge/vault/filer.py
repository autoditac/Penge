"""File a deduplicated document into the vault tree.

Layout (see ADR-0024)::

    <vault_root>/
        .index.json             # hash -> filed path
        .health                 # heartbeat timestamp (RFC 3339, UTC)
        2026/
            unsorted/
                <sha256>-<slug>.pdf
                <sha256>-<slug>.txt   # OCR sidecar
            statements/
                <sha256>-<slug>.pdf
            ...

Filenames are ``{full sha256}-{slug}.{ext}`` so:

* the hash is visible in ``ls`` output and tooling can dedupe by name
  alone (no DB lookup);
* a human-readable slug derived from the original filename keeps the
  vault browseable;
* the year folder reflects when the document was *received*, not the
  document date — the rules-based classifier (#42) may move documents
  into a richer hierarchy later.
"""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from penge.vault.dedupe import HashIndex, IndexEntry, sha256_of_file
from penge.vault.errors import FilerError

log = logging.getLogger("penge.vault.filer")

#: Default classification until ADR-0024 + issue #42 ship a rules-based
#: classifier that can pick ``statements``, ``invoices``, ``payslips``,
#: ``tax``, etc. based on OCR text.
UNSORTED_TYPE = "unsorted"

#: Hard cap on the slug derived from the original filename. Long enough
#: to keep documents identifiable on disk, short enough to keep the full
#: filename (hash + dash + slug + ext) under common 255-byte limits.
MAX_SLUG_LEN = 64

_SLUG_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class FilerResult:
    """Outcome of attempting to file a single document."""

    sha256: str
    filed_path: Path | None
    duplicate: bool
    document_type: str


def slugify(name: str) -> str:
    """Return a filesystem-safe lowercase slug derived from *name*.

    Non-alphanumeric runs collapse to a single hyphen, leading/trailing
    hyphens are stripped, and the result is truncated to
    :data:`MAX_SLUG_LEN`. Empty inputs yield ``"document"``.
    """

    base = _SLUG_RE.sub("-", name.lower()).strip("-")
    if not base:
        base = "document"
    return base[:MAX_SLUG_LEN].rstrip("-") or "document"


def file_document(
    source: Path,
    *,
    vault_root: Path,
    index: HashIndex,
    ocr_text: str,
    document_type: str = UNSORTED_TYPE,
    now: datetime | None = None,
) -> FilerResult:
    """Move *source* into the vault tree and record it in *index*.

    Args:
        source: The freshly-arrived file in the inbox.
        vault_root: Root of the on-disk vault.
        index: Hash index sidecar; consulted for dedup and updated
            on success.
        ocr_text: Searchable text written next to the document as
            ``<hash>-<slug>.txt``. Empty strings are still written so
            tools always find a sidecar.
        document_type: Classification bucket — defaults to
            :data:`UNSORTED_TYPE`.
        now: Override the "filed at" timestamp; useful in tests.

    Returns:
        :class:`FilerResult` describing the outcome. ``duplicate=True``
        means the source has been *removed* from the inbox without
        creating a new copy.

    Raises:
        FilerError: On filesystem errors that prevent filing.
    """

    if not source.is_file():
        raise FilerError(f"source is not a file: {source}")

    sha256 = sha256_of_file(source)
    if index.contains(sha256):
        log.info("vault.filer.duplicate sha256=%s source=%s", sha256, source)
        try:
            source.unlink()
        except OSError as exc:
            raise FilerError(f"failed to remove duplicate {source}: {exc}") from exc
        return FilerResult(
            sha256=sha256, filed_path=None, duplicate=True, document_type=document_type
        )

    timestamp = now or datetime.now(UTC)
    year = timestamp.strftime("%Y")
    suffix = source.suffix.lower() or ".bin"
    slug = slugify(source.stem)
    filename = f"{sha256}-{slug}{suffix}"

    target_dir = vault_root / year / document_type
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise FilerError(f"failed to create {target_dir}: {exc}") from exc

    target = target_dir / filename
    sidecar = target_dir / f"{sha256}-{slug}.txt"

    try:
        shutil.move(str(source), str(target))
    except OSError as exc:
        raise FilerError(f"failed to move {source} -> {target}: {exc}") from exc

    try:
        sidecar.write_text(ocr_text, encoding="utf-8")
    except OSError as exc:
        raise FilerError(f"failed to write OCR sidecar {sidecar}: {exc}") from exc

    entry: IndexEntry = {
        "path": str(target.relative_to(vault_root)),
        "size": target.stat().st_size,
        "filed_at": timestamp.isoformat(),
    }
    index.add(sha256, entry)

    log.info(
        "vault.filer.filed sha256=%s filed_path=%s document_type=%s",
        sha256,
        entry["path"],
        document_type,
    )
    return FilerResult(
        sha256=sha256, filed_path=target, duplicate=False, document_type=document_type
    )
