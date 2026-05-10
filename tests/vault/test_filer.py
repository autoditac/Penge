"""Unit tests for :mod:`penge.vault.filer`."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from penge.vault.dedupe import HashIndex
from penge.vault.errors import FilerError
from penge.vault.filer import file_document, slugify


def test_slugify_basic() -> None:
    assert slugify("Q3 2025 Statement.pdf") == "q3-2025-statement-pdf"
    assert slugify("  --- ") == "document"
    assert slugify("åøæ") == "document"
    assert slugify("a" * 200).startswith("a" * 64)
    assert len(slugify("a" * 200)) == 64


def _make_pdf(path: Path, content: bytes = b"%PDF-1.4 hello") -> None:
    path.write_bytes(content)


def test_file_document_files_to_year_unsorted_path(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    vault = tmp_path / "vault"
    inbox.mkdir()
    src = inbox / "Q3 Statement.pdf"
    _make_pdf(src)

    index = HashIndex(vault / ".index.json")
    now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)

    result = file_document(src, vault_root=vault, index=index, ocr_text="hello", now=now)

    assert not result.duplicate
    assert result.filed_path is not None
    assert result.filed_path.parent == vault / "2026" / "unsorted"
    assert result.filed_path.name.startswith(result.sha256)
    assert result.filed_path.name.endswith("-q3-statement.pdf")
    sidecar = result.filed_path.with_suffix(".txt")
    assert sidecar.read_text(encoding="utf-8") == "hello"
    assert not src.exists()  # moved
    assert index.contains(result.sha256)


def test_file_document_dedup_removes_duplicate(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    vault = tmp_path / "vault"
    inbox.mkdir()
    src1 = inbox / "a.pdf"
    src2 = inbox / "b.pdf"
    _make_pdf(src1, b"%PDF-1.4 same")
    _make_pdf(src2, b"%PDF-1.4 same")

    index = HashIndex(vault / ".index.json")

    r1 = file_document(src1, vault_root=vault, index=index, ocr_text="t")
    r2 = file_document(src2, vault_root=vault, index=index, ocr_text="t")

    assert not r1.duplicate
    assert r2.duplicate
    assert r1.sha256 == r2.sha256
    assert r2.filed_path is None
    assert not src2.exists()  # duplicate removed from inbox
    # Only one filed copy exists in the vault.
    pdfs = list(vault.rglob("*.pdf"))
    assert len(pdfs) == 1


def test_file_document_rejects_non_file(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    index = HashIndex(vault / ".index.json")
    with pytest.raises(FilerError):
        file_document(tmp_path / "missing.pdf", vault_root=vault, index=index, ocr_text="")
