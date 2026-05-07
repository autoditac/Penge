"""Tests for `penge.ingest.nordnet`."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from penge.ingest.nordnet import (
    ACCOUNT_KIND_AKTIEDEPOT,
    ACCOUNT_KIND_AKTIESPAREKONTO,
    ACCOUNT_KIND_OPSPARINGSKONTO,
    TXN_KIND_BUY,
    TXN_KIND_CASH_INTEREST,
    TXN_KIND_DEPOSIT,
    TXN_KIND_DIVIDEND,
    TXN_KIND_INTERNAL_TRANSFER,
    TXN_KIND_SELL,
    TXN_KIND_TAX_ASK_CHARGE,
    TXN_KIND_TAX_ASK_PAYMENT,
    TXN_KIND_WITHDRAWAL,
    AccountConfig,
    AccountsConfig,
    ParsedHolding,
    derive_cash_balances,
    instrument_map_from_transactions,
    load_accounts_config,
    parse_holdings,
    parse_holdings_file,
    parse_holdings_filename,
    parse_transactions,
)
from tests.ingest.nordnet._fixture_builders import (
    HLD_HEADER,
    TXN_HEADER,
    hld_row,
    txn_row,
    write_nordnet_csv,
)

# ----- transactions ---------------------------------------------------------


def test_parse_transactions_handles_all_observed_kinds(tmp_path: Path) -> None:
    rows = [
        TXN_HEADER,
        # KØBT — buy
        txn_row(
            id_="1001",
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
            text="FM-1234567",
        ),
        # SOLGT — sell
        txn_row(
            id_="1002",
            book_date="2026-04-05",
            trade_date="2026-04-05",
            depot="99999990",
            type_="SOLGT",
            name="iShares MSCI World",
            isin="IE00B4L5Y983",
            quantity="-50",
            price="60,00",
            amount_ccy="DKK",
            amount="3000,00",
            saldo="12421,00",
        ),
        # UDBYTTE — dividend
        txn_row(
            id_="1003",
            book_date="2026-04-10",
            depot="99999990",
            type_="UDBYTTE",
            name="iShares MSCI World",
            isin="IE00B4L5Y983",
            amount_ccy="DKK",
            amount="123,45",
            saldo="12544,45",
            text="UDBYTTE 0.05 USD/AKSJE",
        ),
        # INDBETALING — external deposit
        txn_row(
            id_="1004",
            book_date="2026-04-11",
            depot="99999990",
            type_="INDBETALING",
            amount="10000,00",
            saldo="22544,45",
            text="ÖVERFÖRING",
        ),
        # HÆVNING — withdrawal (external; no Internal text)
        txn_row(
            id_="1005",
            book_date="2026-04-12",
            depot="99999992",
            type_="HÆVNING",
            amount="-500,00",
            saldo="0",
            text="Udbetaling til konto 12345678",
        ),
        # INDSÆTTELSE — internal transfer (donor side has empty Saldo)
        txn_row(
            id_="1006",
            book_date="2026-04-13",
            depot="99999991",
            type_="INDSÆTTELSE",
            amount="2500,00",
            saldo="2500,00",
            text="Internal from 99999990",
        ),
        # KREDITRENTE — credit interest
        txn_row(
            id_="1007",
            book_date="2026-04-30",
            depot="99999992",
            type_="KREDITRENTE",
            amount="12,34",
            saldo="12,34",
        ),
        # AFKASTSKAT ASK
        txn_row(
            id_="1008",
            book_date="2026-04-30",
            depot="99999991",
            type_="AFKASTSKAT ASK",
            amount="-50,00",
            saldo="2450,00",
        ),
        # SKATTEINDBETALING ASK
        txn_row(
            id_="1009",
            book_date="2026-05-01",
            depot="99999991",
            type_="SKATTEINDBETALING ASK",
            amount="50,00",
            saldo="2500,00",
            text="Internal from 99999990",
        ),
    ]
    csv_path = write_nordnet_csv(tmp_path / "txns.csv", rows)

    parsed = list(parse_transactions(csv_path))
    by_id = {t.nordnet_id: t for t in parsed}
    assert len(parsed) == 9

    assert by_id["1001"].canonical_kind == TXN_KIND_BUY
    assert by_id["1001"].isin == "IE00B4L5Y983"
    assert by_id["1001"].amount == Decimal("-5579.00")
    assert by_id["1001"].amount_currency == "DKK"
    assert by_id["1001"].quantity == Decimal("100")
    assert by_id["1001"].fees == Decimal("29.00")
    assert by_id["1001"].value_date == date(2026, 4, 3)

    assert by_id["1002"].canonical_kind == TXN_KIND_SELL
    assert by_id["1003"].canonical_kind == TXN_KIND_DIVIDEND

    assert by_id["1004"].canonical_kind == TXN_KIND_DEPOSIT
    assert by_id["1004"].counter_account is None

    assert by_id["1005"].canonical_kind == TXN_KIND_WITHDRAWAL
    assert by_id["1005"].counter_account is None

    assert by_id["1006"].canonical_kind == TXN_KIND_INTERNAL_TRANSFER
    assert by_id["1006"].counter_account == "99999990"

    assert by_id["1007"].canonical_kind == TXN_KIND_CASH_INTEREST

    assert by_id["1008"].canonical_kind == TXN_KIND_TAX_ASK_CHARGE
    assert by_id["1009"].canonical_kind == TXN_KIND_TAX_ASK_PAYMENT
    assert by_id["1009"].counter_account == "99999990"


def test_parse_transactions_amount_currency_defaults_to_dkk(tmp_path: Path) -> None:
    rows = [
        TXN_HEADER,
        txn_row(
            id_="1",
            book_date="2026-01-01",
            depot="99999990",
            type_="KREDITRENTE",
            amount="10,00",
            saldo="10,00",
        ),
    ]
    csv_path = write_nordnet_csv(tmp_path / "t.csv", rows)
    parsed = list(parse_transactions(csv_path))
    assert parsed[0].amount_currency == "DKK"


def test_parse_transactions_unknown_type_raises(tmp_path: Path) -> None:
    rows = [
        TXN_HEADER,
        txn_row(
            id_="1",
            book_date="2026-01-01",
            depot="99999990",
            type_="ALIENSPAYMENT",
            amount="1,00",
        ),
    ]
    csv_path = write_nordnet_csv(tmp_path / "t.csv", rows)
    with pytest.raises(ValueError, match="ALIENSPAYMENT"):
        list(parse_transactions(csv_path))


def test_parse_transactions_rejects_wrong_first_header(tmp_path: Path) -> None:
    bad = (("BogusFirstColumn",) + TXN_HEADER[1:],)
    csv_path = write_nordnet_csv(tmp_path / "t.csv", bad)
    with pytest.raises(ValueError, match="BogusFirstColumn"):
        list(parse_transactions(csv_path))


# ----- holdings -------------------------------------------------------------


def test_parse_holdings_round_trip(tmp_path: Path) -> None:
    rows = [
        HLD_HEADER,
        hld_row(
            name="iShares MSCI World",
            currency="EUR",
            quantity="100,5",
            avg_cost="50,00",
            last_price="60,00",
            value_dkk="6030,00",
            return_pct="20,00",
            return_dkk="1005,00",
        ),
        hld_row(
            name="Nordnet One Balance DKK",
            currency="DKK",
            quantity="1,5",
            last_price="100,00",
            value_dkk="150,00",
        ),
    ]
    csv_path = write_nordnet_csv(tmp_path / "h.csv", rows)
    parsed = parse_holdings(csv_path)
    assert len(parsed) == 2
    assert parsed[0] == ParsedHolding(
        name="iShares MSCI World",
        currency="EUR",
        quantity=Decimal("100.5"),
        avg_cost=Decimal("50.00"),
        last_price=Decimal("60.00"),
        market_value_dkk=Decimal("6030.00"),
        return_pct=Decimal("20.00"),
        return_dkk=Decimal("1005.00"),
    )


def test_parse_holdings_filename() -> None:
    account, as_of = parse_holdings_filename("Depotoversigt for kontonummer 60109543, 7.5.2026.csv")
    assert account == "60109543"
    assert as_of == date(2026, 5, 7)


def test_parse_holdings_filename_rejects_non_match() -> None:
    with pytest.raises(ValueError, match="not a Nordnet holdings filename"):
        parse_holdings_filename("transactions.csv")


def test_parse_holdings_file_bundles_metadata(tmp_path: Path) -> None:
    rows = [
        HLD_HEADER,
        hld_row(name="X", currency="DKK", quantity="1"),
    ]
    name = "Depotoversigt for kontonummer 99999990, 7.5.2026.csv"
    csv_path = write_nordnet_csv(tmp_path / name, rows)
    bundle = parse_holdings_file(csv_path)
    assert bundle.account_number == "99999990"
    assert bundle.as_of == date(2026, 5, 7)
    assert len(bundle.holdings) == 1


# ----- ISIN map + cash balances --------------------------------------------


def test_instrument_map_from_transactions(tmp_path: Path) -> None:
    rows = [
        TXN_HEADER,
        txn_row(
            id_="1",
            book_date="2026-04-01",
            depot="99999990",
            type_="KØBT",
            name="iShares MSCI World",
            isin="IE00B4L5Y983",
            amount="-100,00",
            saldo="900,00",
        ),
        txn_row(
            id_="2",
            book_date="2026-04-02",
            depot="99999990",
            type_="UDBYTTE",
            name="iShares MSCI World",
            isin="IE00B4L5Y983",
            amount="5,00",
            saldo="905,00",
        ),
        # row missing ISIN — must not corrupt the map
        txn_row(
            id_="3",
            book_date="2026-04-03",
            depot="99999990",
            type_="KREDITRENTE",
            amount="1,00",
            saldo="906,00",
        ),
    ]
    csv_path = write_nordnet_csv(tmp_path / "t.csv", rows)
    mapping = instrument_map_from_transactions(parse_transactions(csv_path))
    assert mapping == {"iShares MSCI World": "IE00B4L5Y983"}


def test_instrument_map_conflicting_isin_raises(tmp_path: Path) -> None:
    rows = [
        TXN_HEADER,
        txn_row(
            id_="1",
            book_date="2026-04-01",
            depot="99999990",
            type_="KØBT",
            name="Acme Fund",
            isin="DK0000000001",
            amount="-1,00",
        ),
        txn_row(
            id_="2",
            book_date="2026-04-02",
            depot="99999990",
            type_="KØBT",
            name="Acme Fund",
            isin="DK0000000999",
            amount="-1,00",
        ),
    ]
    csv_path = write_nordnet_csv(tmp_path / "t.csv", rows)
    with pytest.raises(ValueError, match="conflicting ISIN"):
        instrument_map_from_transactions(parse_transactions(csv_path))


def test_derive_cash_balances_picks_latest_per_account_currency(
    tmp_path: Path,
) -> None:
    rows = [
        TXN_HEADER,
        # 99999990 / DKK — older first
        txn_row(
            id_="A1",
            book_date="2026-03-01",
            value_date="2026-03-01",
            depot="99999990",
            type_="INDBETALING",
            amount_ccy="DKK",
            amount="100,00",
            saldo="100,00",
        ),
        txn_row(
            id_="A2",
            book_date="2026-04-15",
            value_date="2026-04-15",
            depot="99999990",
            type_="INDBETALING",
            amount_ccy="DKK",
            amount="50,00",
            saldo="150,00",
        ),
        # 99999992 / DKK
        txn_row(
            id_="B1",
            book_date="2026-04-30",
            value_date="2026-04-30",
            depot="99999992",
            type_="KREDITRENTE",
            amount_ccy="DKK",
            amount="1,00",
            saldo="1,00",
        ),
        # row with no Saldo must be skipped
        txn_row(
            id_="C1",
            book_date="2026-05-01",
            value_date="2026-05-01",
            depot="99999990",
            type_="HÆVNING",
            amount_ccy="DKK",
            amount="-25,00",
            saldo="",
            text="Internal to 99999991",
        ),
    ]
    csv_path = write_nordnet_csv(tmp_path / "t.csv", rows)
    balances = derive_cash_balances(parse_transactions(csv_path))
    by_key = {(b.account_number, b.currency): b for b in balances}
    assert by_key[("99999990", "DKK")].saldo == Decimal("150.00")
    assert by_key[("99999990", "DKK")].as_of == date(2026, 4, 15)
    assert by_key[("99999992", "DKK")].saldo == Decimal("1.00")
    # exactly two keys — the no-Saldo row didn't introduce a third.
    assert set(by_key.keys()) == {
        ("99999990", "DKK"),
        ("99999992", "DKK"),
    }


# ----- accounts config ------------------------------------------------------


def test_load_accounts_config_validates_kinds(tmp_path: Path) -> None:
    p = tmp_path / "accounts.yaml"
    p.write_text(
        "accounts:\n"
        '  - number: "1"\n'
        '    entity: "A"\n'
        "    kind: aktiedepot\n"
        '  - number: "2"\n'
        '    entity: "B"\n'
        "    kind: aktiesparekonto\n"
        '  - number: "3"\n'
        '    entity: "A"\n'
        "    kind: opsparingskonto\n",
        encoding="utf-8",
    )
    cfg = load_accounts_config(p)
    assert isinstance(cfg, AccountsConfig)
    assert {a.kind for a in cfg.accounts} == {
        ACCOUNT_KIND_AKTIEDEPOT,
        ACCOUNT_KIND_AKTIESPAREKONTO,
        ACCOUNT_KIND_OPSPARINGSKONTO,
    }
    looked_up = cfg.by_number("2")
    assert isinstance(looked_up, AccountConfig)
    assert looked_up.entity == "B"


def test_load_accounts_config_rejects_unknown_kind(tmp_path: Path) -> None:
    p = tmp_path / "accounts.yaml"
    p.write_text(
        'accounts:\n  - number: "1"\n    entity: "A"\n    kind: bogus\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown account.kind"):
        load_accounts_config(p)


def test_load_accounts_config_rejects_duplicate_numbers(tmp_path: Path) -> None:
    p = tmp_path / "accounts.yaml"
    p.write_text(
        'accounts:\n  - number: "1"\n    entity: "A"\n    kind: aktiedepot\n'
        '  - number: "1"\n    entity: "B"\n    kind: aktiedepot\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate account number"):
        load_accounts_config(p)


def test_example_config_in_repo_is_valid() -> None:
    """The committed sample config must pass validation."""

    repo_root = Path(__file__).resolve().parents[3]
    cfg = load_accounts_config(repo_root / "config" / "nordnet-accounts.example.yaml")
    assert len(cfg.accounts) >= 1
    for a in cfg.accounts:
        assert a.kind in {
            ACCOUNT_KIND_AKTIEDEPOT,
            ACCOUNT_KIND_AKTIESPAREKONTO,
            ACCOUNT_KIND_OPSPARINGSKONTO,
        }
