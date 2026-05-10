"""Unit tests for the vault content-hash dedup index."""

from __future__ import annotations

import json
from pathlib import Path

from penge.vault.dedupe import HashIndex, sha256_of_file


def test_sha256_of_file_matches_expected(tmp_path: Path) -> None:
    p = tmp_path / "x.bin"
    p.write_bytes(b"hello world")
    # echo -n "hello world" | sha256sum
    assert sha256_of_file(p) == ("b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9")


def test_index_round_trips_through_disk(tmp_path: Path) -> None:
    idx_path = tmp_path / ".index.json"
    idx = HashIndex(idx_path)
    assert len(idx) == 0

    idx.add(
        "a" * 64,
        {"path": "2026/unsorted/aaa-foo.pdf", "size": 17, "filed_at": "2026-01-01T00:00:00+00:00"},
    )
    assert len(idx) == 1
    assert idx.contains("a" * 64)
    assert not idx.contains("b" * 64)

    # Reload from disk: state must persist.
    reloaded = HashIndex(idx_path)
    assert reloaded.contains("a" * 64)
    entry = reloaded.get("a" * 64)
    assert entry is not None
    assert entry["size"] == 17

    raw = json.loads(idx_path.read_text(encoding="utf-8"))
    assert "a" * 64 in raw


def test_index_tolerates_unreadable_file(tmp_path: Path) -> None:
    idx_path = tmp_path / ".index.json"
    idx_path.write_text("{not valid json", encoding="utf-8")
    idx = HashIndex(idx_path)
    assert len(idx) == 0
    # Adding still works (overwrites the broken file).
    idx.add(
        "f" * 64,
        {"path": "p", "size": 1, "filed_at": "2026-01-01T00:00:00+00:00"},
    )
    assert idx.contains("f" * 64)
