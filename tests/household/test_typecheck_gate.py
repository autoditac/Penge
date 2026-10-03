"""Prove imported diagnostics are scoped, not weakened for selected files."""

from __future__ import annotations

import subprocess
from pathlib import Path


def test_hook_still_reports_strict_errors_in_every_explicit_file(tmp_path: Path) -> None:
    imported = tmp_path / "imported.py"
    selected = tmp_path / "selected.py"
    imported.write_text('def imported_value() -> int:\n    return "invalid"\n', encoding="utf-8")
    selected.write_text(
        "from imported import imported_value\n"
        'def selected_value() -> int:\n    return "invalid"\n'
        "value: int = imported_value()\n",
        encoding="utf-8",
    )
    command = [
        "mypy",
        "--strict",
        "--ignore-missing-imports",
        "--follow-imports=silent",
        "--no-incremental",
    ]
    only_selected = subprocess.run(  # noqa: S603 — fixed type checker, synthetic temp sources
        [*command, str(selected)],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    assert only_selected.returncode == 1
    assert "selected.py:3: error:" in only_selected.stdout
    assert "imported.py:2: error:" not in only_selected.stdout
    all_explicit = subprocess.run(  # noqa: S603 — full-file gate retains imported module diagnostics
        [*command, str(selected), str(imported)],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    assert all_explicit.returncode == 1
    assert "selected.py:3: error:" in all_explicit.stdout
    assert "imported.py:2: error:" in all_explicit.stdout
