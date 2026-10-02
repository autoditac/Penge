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
from decimal import Decimal
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
    load_records,
)
from penge.ingest.nordnet.parser import parse_holdings_file
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


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    """Engine pointed at the test DB; runs ``alembic upgrade head`` once."""

    assert _DB_URL is not None
    eng = create_engine(_DB_URL)
    env = {**os.environ, "DATABASE_URL": _DB_URL}
    subprocess.run(  # noqa: S603 — fixed migration command in an isolated test database
        ["alembic", "upgrade", "head"],  # noqa: S607
        cwd=REPO_ROOT,
        env=env,
        check=True,
    )
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture(autouse=True)
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


@pytest.fixture
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


@pytest.fixture
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
            text("select external_id, kind from account where provider = :p order by external_id"),
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
            text("select ticker from instrument where kind = 'cash' order by ticker")
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


def test_holdings_only_resolves_prior_snapshot_and_keeps_other_accounts(
    engine: Engine,
    accounts_config: AccountsConfig,
    fixture_csvs: tuple[Path, list[Path]],
    tmp_path: Path,
) -> None:
    txn_path, holdings_paths = fixture_csvs
    load_files(
        engine,
        transactions_csv=txn_path,
        holdings_csvs=holdings_paths,
        accounts_config=accounts_config,
    )
    changed_config = accounts_config.model_copy(
        update={
            "accounts": tuple(
                account.model_copy(update={"name": "Do not rename"})
                if account.number == "99999991"
                else account
                for account in accounts_config.accounts
            )
        }
    )
    next_snapshot = write_nordnet_csv(
        tmp_path / "Depotoversigt for kontonummer 99999990, 8.5.2026.csv",
        [
            HLD_HEADER,
            hld_row(
                name="iShares MSCI World",
                currency="EUR",
                quantity="101",
                value_dkk="6100,00",
            ),
        ],
    )
    result = load_records(
        engine,
        transactions=[],
        holdings=[parse_holdings_file(next_snapshot)],
        accounts_config=changed_config,
    )
    assert result.accounts == 1
    assert result.transactions == 0
    assert result.holding_snapshots == 1
    with engine.connect() as conn:
        assert (
            conn.execute(
                text(
                    "select count(*) from holding_snapshot hs join instrument i "
                    "on i.id = hs.instrument_id where i.kind = 'cash'"
                )
            ).scalar_one()
            == 3
        )
        assert (
            conn.execute(
                text("select quantity from holding_snapshot where as_of = '2026-05-08'")
            ).scalar_one()
            == 101
        )
        assert (
            conn.execute(
                text("select name from account where external_id = '99999991'")
            ).scalar_one()
            == "Aktiesparekonto"
        )


def test_holdings_only_unmapped_is_atomic(
    engine: Engine,
    accounts_config: AccountsConfig,
    tmp_path: Path,
) -> None:
    path = write_nordnet_csv(
        tmp_path / "Depotoversigt for kontonummer 99999990, 8.5.2026.csv",
        [HLD_HEADER, hld_row(name="Unmapped Fund", currency="EUR", quantity="1")],
    )
    with pytest.raises(ValueError, match="no ISIN mapping"):
        load_records(
            engine,
            transactions=[],
            holdings=[parse_holdings_file(path)],
            accounts_config=accounts_config,
        )
    with engine.connect() as conn:
        assert conn.execute(text("select count(*) from account")).scalar_one() == 0


def test_combined_load_rejects_unmapped_position_without_partial_writes(
    engine: Engine,
    accounts_config: AccountsConfig,
    fixture_csvs: tuple[Path, list[Path]],
    tmp_path: Path,
) -> None:
    transactions_path, _ = fixture_csvs
    holdings_path = write_nordnet_csv(
        tmp_path / "Depotoversigt for kontonummer 99999990, 9.5.2026.csv",
        [
            HLD_HEADER,
            hld_row(name="iShares MSCI World", currency="EUR", quantity="1"),
            hld_row(name="Unknown Fund", currency="EUR", quantity="1"),
        ],
    )
    with pytest.raises(ValueError, match="no ISIN mapping"):
        load_files(
            engine,
            transactions_csv=transactions_path,
            holdings_csvs=[holdings_path],
            accounts_config=accounts_config,
        )
    with engine.connect() as conn:
        assert conn.execute(text('select count(*) from "transaction"')).scalar_one() == 0
        assert conn.execute(text("select count(*) from holding_snapshot")).scalar_one() == 0


def test_complete_snapshot_zeros_sold_security_and_same_date_reimport_restores_it(
    engine: Engine,
    accounts_config: AccountsConfig,
    tmp_path: Path,
) -> None:
    trades = write_nordnet_csv(
        tmp_path / "trades.csv",
        [
            TXN_HEADER,
            txn_row(
                id_="FIRST",
                book_date="2026-05-01",
                depot="99999990",
                type_="KØBT",
                name="Synthetic Alpha",
                isin="IE00B4L5Y983",
                amount="-10,00",
                saldo="90,00",
            ),
            txn_row(
                id_="SECOND",
                book_date="2026-05-01",
                depot="99999990",
                type_="KØBT",
                name="Synthetic Beta",
                isin="IE00B3RBWM25",
                amount="-20,00",
                saldo="70,00",
            ),
        ],
    )
    first = write_nordnet_csv(
        tmp_path / "Depotoversigt for kontonummer 99999990, 5.5.2026.csv",
        [
            HLD_HEADER,
            hld_row(
                name="Synthetic Alpha",
                currency="EUR",
                quantity="2",
                last_price="5,00",
                value_dkk="100,00",
            ),
            hld_row(
                name="Synthetic Beta",
                currency="EUR",
                quantity="3",
                last_price="6,00",
                value_dkk="200,00",
            ),
        ],
    )
    load_files(
        engine,
        transactions_csv=trades,
        holdings_csvs=[first],
        accounts_config=accounts_config,
    )
    next_date = tmp_path / "Depotoversigt for kontonummer 99999990, 7.5.2026.csv"
    write_nordnet_csv(
        next_date,
        [
            HLD_HEADER,
            hld_row(
                name="Synthetic Alpha",
                currency="EUR",
                quantity="4",
                last_price="7,00",
                value_dkk="250,00",
            ),
        ],
    )
    result = load_records(
        engine,
        transactions=[],
        holdings=[parse_holdings_file(next_date)],
        accounts_config=accounts_config,
    )
    assert result.holding_snapshots == 2

    def snapshots() -> list[tuple[str, Decimal, Decimal | None, Decimal | None]]:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "select trim(i.isin) as isin, hs.quantity, hs.market_value, hs.price "
                    "from holding_snapshot hs join instrument i on i.id = hs.instrument_id "
                    "join account a on a.id = hs.account_id "
                    "where a.external_id = '99999990' and hs.as_of = '2026-05-07' "
                    "and i.kind = 'security' order by isin"
                )
            ).all()
        return [(r.isin, r.quantity, r.market_value, r.price) for r in rows]

    assert snapshots() == [
        ("IE00B3RBWM25", Decimal("0"), Decimal("0"), None),
        ("IE00B4L5Y983", Decimal("4"), Decimal("250"), Decimal("7")),
    ]
    with engine.connect() as conn:
        assert (
            conn.execute(
                text(
                    "select count(*) from holding_snapshot hs join instrument i "
                    "on i.id = hs.instrument_id where i.kind = 'cash'"
                )
            ).scalar_one()
            == 1
        )
        assert (
            conn.execute(
                text(
                    "select quantity from holding_snapshot hs join instrument i "
                    "on i.id = hs.instrument_id where i.isin = 'IE00B3RBWM25' "
                    "and hs.as_of = '2026-05-05'"
                )
            ).scalar_one()
            == 3
        )

    # Correct a previously incomplete full export on the same date.
    write_nordnet_csv(
        next_date,
        [
            HLD_HEADER,
            hld_row(
                name="Synthetic Alpha",
                currency="EUR",
                quantity="4",
                last_price="7,00",
                value_dkk="250,00",
            ),
            hld_row(
                name="Synthetic Beta",
                currency="EUR",
                quantity="1",
                last_price="8,00",
                value_dkk="80,00",
            ),
        ],
    )
    corrected = load_records(
        engine,
        transactions=[],
        holdings=[parse_holdings_file(next_date)],
        accounts_config=accounts_config,
    )
    assert corrected.holding_snapshots == 2
    assert snapshots() == [
        ("IE00B3RBWM25", Decimal("1"), Decimal("80"), Decimal("8")),
        ("IE00B4L5Y983", Decimal("4"), Decimal("250"), Decimal("7")),
    ]
    # Repeating the incomplete export must zero the restored position again.
    write_nordnet_csv(
        next_date,
        [
            HLD_HEADER,
            hld_row(
                name="Synthetic Alpha",
                currency="EUR",
                quantity="4",
                last_price="7,00",
                value_dkk="250,00",
            ),
        ],
    )
    assert (
        load_records(
            engine,
            transactions=[],
            holdings=[parse_holdings_file(next_date)],
            accounts_config=accounts_config,
        ).holding_snapshots
        == 2
    )
    assert snapshots()[0] == ("IE00B3RBWM25", Decimal("0"), Decimal("0"), None)


def test_same_name_with_two_isins_rejects_snapshot_atomically(
    engine: Engine,
    accounts_config: AccountsConfig,
    tmp_path: Path,
) -> None:
    trades = write_nordnet_csv(
        tmp_path / "trades.csv",
        [
            TXN_HEADER,
            txn_row(
                id_="FIRST",
                book_date="2026-05-01",
                depot="99999990",
                type_="KØBT",
                name="Ambiguous Fund",
                isin="IE00B4L5Y983",
                amount="-10,00",
            ),
            txn_row(
                id_="SECOND",
                book_date="2026-05-02",
                depot="99999990",
                type_="KØBT",
                name="Ambiguous Fund",
                isin="IE00B3RBWM25",
                amount="-10,00",
            ),
        ],
    )
    holdings = write_nordnet_csv(
        tmp_path / "Depotoversigt for kontonummer 99999990, 7.5.2026.csv",
        [HLD_HEADER, hld_row(name="Ambiguous Fund", currency="EUR", quantity="1")],
    )
    with pytest.raises(ValueError, match="conflicting Nordnet holding instrument"):
        load_files(
            engine,
            transactions_csv=trades,
            holdings_csvs=[holdings],
            accounts_config=accounts_config,
        )
    with engine.connect() as conn:
        assert conn.execute(text("select count(*) from holding_snapshot")).scalar_one() == 0
        assert conn.execute(text('select count(*) from "transaction"')).scalar_one() == 0


def test_duplicate_account_date_files_cannot_replace_each_other(
    engine: Engine,
    accounts_config: AccountsConfig,
    fixture_csvs: tuple[Path, list[Path]],
) -> None:
    transactions, holdings = fixture_csvs
    with pytest.raises(ValueError, match="duplicate Nordnet holdings account/date"):
        load_files(
            engine,
            transactions_csv=transactions,
            holdings_csvs=[holdings[0], holdings[0]],
            accounts_config=accounts_config,
        )
    with engine.connect() as conn:
        assert conn.execute(text("select count(*) from holding_snapshot")).scalar_one() == 0


def test_combined_load_preserves_mappings_for_multiple_dates_same_account(
    engine: Engine,
    accounts_config: AccountsConfig,
    tmp_path: Path,
) -> None:
    transactions = write_nordnet_csv(
        tmp_path / "trades.csv",
        [
            TXN_HEADER,
            txn_row(
                id_="ALPHA",
                book_date="2026-05-01",
                depot="99999990",
                type_="KØBT",
                name="Synthetic Alpha",
                isin="IE00B4L5Y983",
                amount="-10,00",
            ),
            txn_row(
                id_="BETA",
                book_date="2026-05-02",
                depot="99999990",
                type_="KØBT",
                name="Synthetic Beta",
                isin="IE00B3RBWM25",
                amount="-20,00",
            ),
        ],
    )
    first = write_nordnet_csv(
        tmp_path / "Depotoversigt for kontonummer 99999990, 5.5.2026.csv",
        [
            HLD_HEADER,
            hld_row(name="Synthetic Alpha", currency="EUR", quantity="2", value_dkk="100,00"),
        ],
    )
    second = write_nordnet_csv(
        tmp_path / "Depotoversigt for kontonummer 99999990, 7.5.2026.csv",
        [
            HLD_HEADER,
            hld_row(name="Synthetic Beta", currency="EUR", quantity="3", value_dkk="200,00"),
        ],
    )

    result = load_files(
        engine,
        transactions_csv=transactions,
        holdings_csvs=[second, first],
        accounts_config=accounts_config,
    )

    assert result.holding_snapshots == 3  # two positions and sold Alpha
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "select hs.as_of, trim(i.isin) as isin, hs.quantity, hs.market_value "
                "from holding_snapshot hs join instrument i on i.id = hs.instrument_id "
                "where i.kind = 'security' order by hs.as_of, isin"
            )
        ).all()
    assert [(r.as_of.isoformat(), r.isin, r.quantity, r.market_value) for r in rows] == [
        ("2026-05-05", "IE00B4L5Y983", Decimal("2"), Decimal("100")),
        ("2026-05-07", "IE00B3RBWM25", Decimal("3"), Decimal("200")),
        ("2026-05-07", "IE00B4L5Y983", Decimal("0"), Decimal("0")),
    ]


def test_header_only_requires_prior_security_not_just_existing_account(
    engine: Engine,
    accounts_config: AccountsConfig,
    tmp_path: Path,
) -> None:
    transactions = write_nordnet_csv(
        tmp_path / "cash-only.csv",
        [
            TXN_HEADER,
            txn_row(
                id_="CASH",
                book_date="2026-05-01",
                depot="99999990",
                type_="INDBETALING",
                amount="100,00",
                saldo="100,00",
            ),
        ],
    )
    load_files(
        engine,
        transactions_csv=transactions,
        holdings_csvs=[],
        accounts_config=accounts_config,
    )
    empty = write_nordnet_csv(
        tmp_path / "Depotoversigt for kontonummer 99999990, 7.5.2026.csv",
        [HLD_HEADER],
    )
    with pytest.raises(ValueError, match="prior mapped security snapshot"):
        load_records(
            engine,
            transactions=[],
            holdings=[parse_holdings_file(empty)],
            accounts_config=accounts_config,
        )
    with engine.connect() as conn:
        assert (
            conn.execute(
                text("select count(*) from holding_snapshot where as_of = '2026-05-07'")
            ).scalar_one()
            == 0
        )
