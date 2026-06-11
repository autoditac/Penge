"""Source auto-detection tests (no database required)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from penge.api.imports.detect import (
    SOURCE_GROWNEY,
    SOURCE_MANUAL_BALANCES,
    SOURCE_NORDNET_TRANSACTIONS,
    SOURCE_PFA,
    UnsupportedSourceError,
    detect_source,
)
from tests.ingest.nordnet._fixture_builders import (
    HLD_HEADER,
    TXN_HEADER,
    hld_row,
    txn_row,
    write_nordnet_csv,
)

GROWNEY_PDF = (
    Path(__file__).resolve().parents[2] / "ingest" / "growney" / "fixtures"
) / "sample_depotauszug.pdf"
PFA_PDF = (
    Path(__file__).resolve().parents[2] / "ingest" / "pfa" / "fixtures"
) / "sample_pensionsoversigt.pdf"


def test_detects_nordnet_transactions_csv(tmp_path: Path) -> None:
    path = tmp_path / "transactions-export.csv"
    write_nordnet_csv(
        path,
        [
            TXN_HEADER,
            txn_row(
                id_="100",
                book_date="2026-05-02",
                depot="99999990",
                type_="INDBETALING",
                amount_ccy="DKK",
                amount="1.000",
            ),
        ],
    )
    assert detect_source(path) == SOURCE_NORDNET_TRANSACTIONS


def test_rejects_nordnet_holdings_csv(tmp_path: Path) -> None:
    path = tmp_path / "Depotoversigt for kontonummer 99999990, 7.5.2026.csv"
    write_nordnet_csv(
        path,
        [
            HLD_HEADER,
            hld_row(name="Synthetic ETF", currency="DKK", quantity="10"),
        ],
    )
    with pytest.raises(UnsupportedSourceError):
        detect_source(path)


def test_detects_growney_pdf() -> None:
    assert detect_source(GROWNEY_PDF) == SOURCE_GROWNEY


def test_detects_pfa_pdf() -> None:
    assert detect_source(PFA_PDF) == SOURCE_PFA


def test_detects_manual_balances_json(tmp_path: Path) -> None:
    path = tmp_path / "balances.json"
    path.write_text(
        json.dumps(
            {
                "balances": [
                    {
                        "entity": "Owner A",
                        "account_name": "Cash",
                        "currency": "EUR",
                        "as_of": "2026-06-01",
                        "balance": "123.45",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert detect_source(path) == SOURCE_MANUAL_BALANCES


def test_unknown_text_file_detects_nothing(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("just some notes, not a statement", encoding="utf-8")
    assert detect_source(path) is None


def test_json_without_balances_key_detects_nothing(tmp_path: Path) -> None:
    path = tmp_path / "other.json"
    path.write_text(json.dumps({"accounts": []}), encoding="utf-8")
    assert detect_source(path) is None
