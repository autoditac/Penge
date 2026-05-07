"""Integration tests for the Nordnet → Postgres loader.

These exercise SQLAlchemy + Postgres-specific features (UUID
PKs, ``ON CONFLICT``) and need a real Postgres reachable via
``PENGE_TEST_DATABASE_URL`` (or ``DATABASE_URL``). The test
fixture runs ``alembic upgrade head`` once per session against
that database.

When neither env var is set, the entire module is skipped — local
``pytest`` runs without a database remain green.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from penge.ingest.nordnet import (
    ACCOUNT_KIND_AKTIEDEPOT,
    ACCOUNT_KIND_AKTIESPAREKONTO,
    ACCOUNT_KIND_OPSPARINGSKONTO,
)
from penge.ingest.nordnet.config import AccountsConfig, load_accounts_config
from penge.ingest.nordnet.loader import (
    CASH_TICKER_PREFIX,
    PROVIDER,
    UnknownAccountError,
    load_files,
)
from tests.ingest.nordnet._fixture_builders import (
    HLD_HEADER,
    TXN_HEADER,
    hld_row,
    txn_row,
    write_nordnet_csv,
)

_DB_URL = os.environ.get("PENGE_TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")

pytestmark = pytest.mark.skipif(
    _DB_URL is None,
    reason="set PENGE_TEST_DATABASE_URL or DATABASE_URL to run loader tests",
)

REPO_ROOT = Path(__file__).resolve().parents[3]


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session")  # type: ignore[untyped-decorator]
def engine() -> Iterator[Engine]:
    """Engine pointed at the test DB; runs ``alembic upgrade head`` once."""

    assert _DB_URL is not None
    eng = create_engine(_DB_URL)
    env = {**os.environ, "DATABASE_URL": _DB_URL}
    subprocess.run(  # noqa: S603
        ["alembic", "upgrade", "head"],  # noqa: S607
        cwd=REPO_ROOT,
        env=env,
        check=True,
    )
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture(autouse=True)  # type: ignore[untyped-decorator]
def _truncate(engine: Engine) -> Iterator[None]:
    """Wipe tables before each test — keeps tests independent."""

    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE TABLE holding_snapshot, transaction, instrument, "
                "account, entity RESTART IDENTITY CASCADE"
            )
        )
    yield


@pytest.fixture  # type: ignore[untyped-decorator]
def accounts_config(tmp_path: Path) -> AccountsConfig:
    """Synthetic config matching the fixture data below."""

    p = tmp_path / "accounts.yaml"
    p.write_text(
        textwrap.dedent(
            """
            accounts:
              - number: "99999990"
                entity: "Owner A"
                kind: aktiedepot
                currency: DKK
                name: "Aktiedepot"
              - number: "99999991"
                entity: "Owner A"
                kind: aktiesparekonto
                currency: DKK
                name: "Aktiesparekonto"
              - number: "99999992"
                entity: "Owner A"
                kind: opsparingskonto
                currency: DKK
                name: "Opsparingskonto"
            """
        ).strip(),
        encoding="utf-8",
    )
    return load_accounts_config(p)


@pytest.fixture  # type: ignore[untyped-decorator]
def fixture_csvs(tmp_path: Path) -> tuple[Path, list[Path]]:
    """A small but representative pair of CSVs.

    Covers: buy with ISIN, dividend, internal transfer (both legs),
    cash interest, ASK tax (charge + payment), an external deposit
    and withdrawal, plus a holdings CSV per depot.
    """

    txn_rows = [
        TXN_HEADER,
        txn_row(
            id_="T1",
            book_date="2026-04-01",
            trade_date="2026-04-01",
            value_date="2026-04-03",
            depot="99999990",
            type_="KØBT",
            name="iShares MSCI World",
            isin="IE00B4L5Y983",
            quantity="100",
            price="55,50",
            fees="29,00",
            amount_ccy="DKK",
            amount="-5579,00",
            saldo="9421,00",
        ),
        txn_row(
            id_="T2",
            book_date="2026-04-10",
            depot="99999990",
            type_="UDBYTTE",
            name="iShares MSCI World",
            isin="IE00B4L5Y983",
            amount_ccy="DKK",
            amount="123,45",
            saldo="9544,45",
        ),
        # External deposit (cash account)
        txn_row(
            id_="T3",
            book_date="2026-04-11",
            value_date="2026-04-11",
            depot="99999992",
            type_="INDBETALING",
            amount="10000,00",
            saldo="10000,00",
        ),
        # External withdrawal
        txn_row(
            id_="T4",
            book_date="2026-04-12",
            value_date="2026-04-12",
            depot="99999992",
            type_="HÆVNING",
            amount="-500,00",
            saldo="9500,00",
            text="Udbetaling til konto 12345678",
        ),
        # Internal transfer (both legs)
        txn_row(
            id_="T5",
            book_date="2026-04-13",
            value_date="2026-04-13",
            depot="99999992",
            type_="HÆVNING",
            amount="-2500,00",
            saldo="7000,00",
            text="Internal to 99999991",
        ),
        txn_row(
            id_="T6",
            book_date="2026-04-13",
            value_date="2026-04-13",
            depot="99999991",
            type_="INDSÆTTELSE",
            amount="2500,00",
            saldo="2500,00",
            text="Internal from 99999992",
        ),
        # Cash interest
        txn_row(
            id_="T7",
            book_date="2026-04-30",
            value_date="2026-04-30",
            depot="99999992",
            type_="KREDITRENTE",
            amount="12,34",
            saldo="7012,34",
        ),
        # ASK tax
        txn_row(
            id_="T8",
            book_date="2026-04-30",
            value_date="2026-04-30",
            depot="99999991",
            type_="AFKASTSKAT ASK",
            amount="-50,00",
            saldo="2450,00",
        ),
        txn_row(
            id_="T9",
            book_date="2026-05-01",
            value_date="2026-05-01",
            depot="99999991",
            type_="SKATTEINDBETALING ASK",
            amount="50,00",
            saldo="2500,00",
            text="Internal from 99999992",
        ),
    ]
    txn_path = write_nordnet_csv(tmp_path / "txns.csv", txn_rows)

    hld_paths: list[Path] = []
    hld_rows = [
        HLD_HEADER,
        hld_row(
            name="iShares MSCI World",
            currency="EUR",
            quantity="100",
            avg_cost="50,00",
            last_price="60,00",
            value_dkk="6030,00",
        ),
    ]
    hld_paths.append(
        write_nordnet_csv(
            tmp_path / "Depotoversigt for kontonummer 99999990, 7.5.2026.csv",
            hld_rows,
        )
    )

    return txn_path, hld_paths


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


def test_load_writes_canonical_records(
    engine: Engine,
    accounts_config: AccountsConfig,
    fixture_csvs: tuple[Path, list[Path]],
) -> None:
    txn_path, hld_paths = fixture_csvs
    result = load_files(
        engine,
        transactions_csv=txn_path,
        holdings_csvs=hld_paths,
        accounts_config=accounts_config,
    )

    assert result.entities == 1
    assert result.accounts == 3
    # 1 security + 1 cash currency = 2
    assert result.instruments == 2
    assert result.transactions == 9
    # 1 real holding + 3 cash sub-balances (one per account)
    assert result.holding_snapshots == 4

    with engine.connect() as conn:
        # accounts have correct kinds
        rows = conn.execute(
            text(
                "select external_id, kind from account where provider = :p " "order by external_id"
            ),
            {"p": PROVIDER},
        ).all()
        assert [(r.external_id, r.kind) for r in rows] == [
            ("99999990", ACCOUNT_KIND_AKTIEDEPOT),
            ("99999991", ACCOUNT_KIND_AKTIESPAREKONTO),
            ("99999992", ACCOUNT_KIND_OPSPARINGSKONTO),
        ]

        # internal-transfer rows preserve counter-account on counterparty
        ct = conn.execute(
            text(
                "select external_id, counterparty from transaction "
                "where kind = 'internal_transfer' order by external_id"
            )
        ).all()
        assert {r.external_id: r.counterparty for r in ct} == {
            "T5": "nordnet:99999991",
            "T6": "nordnet:99999992",
        }

        # cash instruments materialised
        cash = conn.execute(
            text("select ticker from instrument where kind = 'cash' " "order by ticker")
        ).all()
        assert [r.ticker for r in cash] == [f"{CASH_TICKER_PREFIX}DKK"]

        # one cash holding_snapshot per account
        cash_hldgs = conn.execute(
            text(
                "select count(*) from holding_snapshot hs "
                "join instrument i on i.id = hs.instrument_id "
                "where i.kind = 'cash'"
            )
        ).scalar_one()
        assert cash_hldgs == 3


def test_load_is_idempotent(
    engine: Engine,
    accounts_config: AccountsConfig,
    fixture_csvs: tuple[Path, list[Path]],
) -> None:
    txn_path, hld_paths = fixture_csvs

    def _counts() -> dict[str, int]:
        with engine.connect() as conn:
            return {
                tbl: conn.execute(
                    text(f"select count(*) from {tbl}")  # noqa: S608
                ).scalar_one()
                for tbl in (
                    "entity",
                    "account",
                    "instrument",
                    "transaction",
                    "holding_snapshot",
                )
            }

    load_files(
        engine,
        transactions_csv=txn_path,
        holdings_csvs=hld_paths,
        accounts_config=accounts_config,
    )
    after_first = _counts()

    load_files(
        engine,
        transactions_csv=txn_path,
        holdings_csvs=hld_paths,
        accounts_config=accounts_config,
    )
    after_second = _counts()

    assert after_first == after_second


def test_load_rejects_unknown_account(
    engine: Engine,
    accounts_config: AccountsConfig,
    tmp_path: Path,
) -> None:
    bad_rows = [
        TXN_HEADER,
        txn_row(
            id_="X1",
            book_date="2026-04-01",
            depot="00000000",  # not in config
            type_="KREDITRENTE",
            amount="1,00",
            saldo="1,00",
        ),
    ]
    bad_csv = write_nordnet_csv(tmp_path / "bad.csv", bad_rows)
    with pytest.raises(UnknownAccountError, match="00000000"):
        load_files(
            engine,
            transactions_csv=bad_csv,
            holdings_csvs=[],
            accounts_config=accounts_config,
        )
