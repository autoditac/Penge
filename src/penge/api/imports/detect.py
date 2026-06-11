"""Source auto-detection for uploaded statements.

Cheap, deterministic heuristics over the original filename and the
file's leading bytes. An explicit ``source`` form field on upload
always wins (see :mod:`penge.api.imports.routes`); detection only
fills the gap. Undetectable files are rejected, never guessed.

Nordnet *holdings* CSVs are recognised but rejected with a pointed
message: the loader resolves instruments through transaction history,
so a holdings-only session would silently skip unmapped positions
(see ADR-0037). They stay on the CLI path for now.
"""

from __future__ import annotations

import contextlib
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

SOURCE_NORDNET_TRANSACTIONS = "nordnet_transactions"
SOURCE_GROWNEY = "growney"
SOURCE_PFA = "pfa"
SOURCE_MANUAL_BALANCES = "manual_balances"

KNOWN_SOURCES = (
    SOURCE_NORDNET_TRANSACTIONS,
    SOURCE_GROWNEY,
    SOURCE_PFA,
    SOURCE_MANUAL_BALANCES,
)

_PDF_MAGIC = b"%PDF"
_UTF16_LE_BOM = b"\xff\xfe"

# How much of the file detection may read. Nordnet headers and the
# manual-balances JSON shape show up in the first couple of KiB; PDF
# keyword sniffing reads the whole first page via pdfplumber instead.
_HEAD_BYTES = 8192


class UnsupportedSourceError(Exception):
    """A recognised file type that import sessions deliberately reject."""


def _detect_pdf(path: Path) -> str | None:
    """Distinguish Growney/Sutor from PFA by first-page keywords."""
    # pdfplumber comes from the parsers group; imported lazily like
    # the parsers themselves do so detection failures stay readable.
    import pdfplumber

    try:
        with pdfplumber.open(path) as pdf:
            if not pdf.pages:
                return None
            text = pdf.pages[0].extract_text() or ""
    except Exception:
        return None
    lowered = text.lower()
    if "sutor" in lowered or "growney" in lowered:
        return SOURCE_GROWNEY
    if "pensionsoversigt" in lowered or lowered.startswith("pfa") or " pfa " in lowered:
        return SOURCE_PFA
    return None


def _detect_utf16_csv(head: bytes) -> str | None:
    """Nordnet exports: UTF-16LE BOM, tab-separated."""
    try:
        text = head.decode("utf-16")
    except UnicodeDecodeError:
        return None
    lines = text.splitlines()
    first_line = lines[0] if lines else ""
    columns = [c.strip() for c in first_line.split("\t")]
    if columns and columns[0] == "Id" and "Bogføringsdag" in columns:
        return SOURCE_NORDNET_TRANSACTIONS
    if columns and columns[0] == "Navn":
        raise UnsupportedSourceError(
            "Nordnet holdings CSVs are not supported as import sessions; "
            "load them via the penge-nordnet CLI together with a "
            "transactions CSV (see ADR-0037)."
        )
    return None


def _detect_json(head: bytes) -> str | None:
    """Manual balances: a JSON object with a ``balances`` list."""
    try:
        text = head.decode("utf-8")
    except UnicodeDecodeError:
        return None
    stripped = text.lstrip()
    if not stripped.startswith("{"):
        return None
    # The head may truncate the document; a key probe is enough.
    if '"balances"' not in stripped:
        return None
    # A truncated-but-shaped-right head is accepted; staging validates
    # the full document.
    with contextlib.suppress(json.JSONDecodeError):
        json.loads(text)
    return SOURCE_MANUAL_BALANCES


def detect_source(path: Path) -> str | None:
    """Best-effort source detection; ``None`` when nothing matches.

    Raises :class:`UnsupportedSourceError` for file types that are
    recognised but deliberately not importable via sessions.
    """
    with path.open("rb") as fh:
        head = fh.read(_HEAD_BYTES)
    if head.startswith(_PDF_MAGIC):
        return _detect_pdf(path)
    if head.startswith(_UTF16_LE_BOM):
        return _detect_utf16_csv(head)
    return _detect_json(head)
