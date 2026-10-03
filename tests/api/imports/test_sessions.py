"""End-to-end import-session tests against a real Postgres.

Harness fixtures (``engine``, ``client``) come from ``conftest.py``;
the module is skipped without a test database. All fixture data is
synthetic.
"""

from __future__ import annotations

import json
import textwrap
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from penge.api.imports import commit as commit_mod
from penge.ops.net_worth_refresh import exclusive_lock
from tests.api.imports.conftest import DB_URL, REPO_ROOT, manual_json, upload
from tests.ingest.nordnet._fixture_builders import (
    HLD_HEADER,
    TXN_HEADER,
    hld_row,
    txn_row,
    write_nordnet_csv,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from fastapi.testclient import TestClient
    from sqlalchemy.engine import Engine

    from penge.api.imports import store

pytestmark = pytest.mark.skipif(
    DB_URL is None,
    reason="set PENGE_TEST_DATABASE_URL or DATABASE_URL to run import-session tests",
)

GROWNEY_PDF = REPO_ROOT / "tests" / "ingest" / "growney" / "fixtures" / "sample_depotauszug.pdf"
PFA_PDF = REPO_ROOT / "tests" / "ingest" / "pfa" / "fixtures" / "sample_pensionsoversigt.pdf"

DEPOT = "99999990"


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def nordnet_csv(tmp_path: Path) -> Path:
    """Synthetic two-row Nordnet transactions export."""
    rows = [
        TXN_HEADER,
        txn_row(
            id_="T1",
            book_date="2026-05-02",
            value_date="2026-05-02",
            depot=DEPOT,
            type_="INDBETALING",
            amount="10000,00",
            saldo="10000,00",
        ),
        txn_row(
            id_="T2",
            book_date="2026-05-03",
            value_date="2026-05-03",
            depot=DEPOT,
            type_="HÆVNING",
            amount="-500,00",
            saldo="9500,00",
            text="Udbetaling til konto 12345678",
        ),
    ]
    return write_nordnet_csv(tmp_path / "transactions.csv", rows)


@pytest.fixture
def nordnet_accounts_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Accounts config for DEPOT, exported via the env knob."""
    path = tmp_path / "accounts.yaml"
    path.write_text(
        textwrap.dedent(
            f"""
            accounts:
              - number: "{DEPOT}"
                entity: "Owner A"
                kind: aktiedepot
                currency: DKK
                name: "Aktiedepot"
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PENGE_NORDNET_ACCOUNTS_CONFIG", str(path))
    return path


# --------------------------------------------------------------------------- #
# Nordnet round-trip
# --------------------------------------------------------------------------- #


def test_nordnet_upload_commit_roundtrip(
    client: TestClient,
    engine: Engine,
    nordnet_csv: Path,
    nordnet_accounts_yaml: Path,
    tmp_path: Path,
) -> None:
    _ = nordnet_accounts_yaml
    created = upload(client, nordnet_csv)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["source"] == "nordnet_transactions"
    assert body["status"] == "staged"
    assert body["row_counts"] == {"total": 2, "ok": 2, "warning": 0, "error": 0, "excluded": 0}
    assert {r["kind"] for r in body["rows"]} == {"transaction"}
    # Decimals are staged as strings, never floats.
    assert body["rows"][0]["payload"]["amount"] == "10000.00"

    committed = client.post(f"/imports/{body['id']}/commit")
    assert committed.status_code == 200, committed.text
    counts = committed.json()["counts"]
    assert counts["transactions"] == 2
    assert committed.json()["session"]["status"] == "committed"
    assert committed.json()["session"]["committed_at"] is not None
    assert (tmp_path / "refresh-state" / "pending").exists()

    with engine.connect() as conn:
        n_txns = conn.execute(text('select count(*) from "transaction"')).scalar_one()
    assert n_txns == 2


def test_import_commit_returns_503_while_refresh_lock_is_held(
    client: TestClient,
    engine: Engine,
    nordnet_csv: Path,
    nordnet_accounts_yaml: Path,
    tmp_path: Path,
) -> None:
    _ = nordnet_accounts_yaml
    created = upload(client, nordnet_csv)
    assert created.status_code == 201

    state_dir = tmp_path / "refresh-state"
    with exclusive_lock(state_dir / "refresh.lock"):
        response = client.post(f"/imports/{created.json()['id']}/commit")

    assert response.status_code == 503
    assert response.json()["detail"] == "refresh lock is already held"
    assert not (state_dir / "pending").exists()
    with engine.connect() as conn:
        assert conn.execute(text('select count(*) from "transaction"')).scalar_one() == 0


def test_import_commit_retains_pending_marker_after_partial_write(
    client: TestClient,
    nordnet_csv: Path,
    nordnet_accounts_yaml: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = nordnet_accounts_yaml
    created = upload(client, nordnet_csv)
    assert created.status_code == 201

    def fail_after_write(
        engine: Engine,
        session: store.SessionRecord,
        rows: Sequence[store.RowRecord],
        *,
        entity_name: str | None = None,
        account_name: str | None = None,
        on_write: Callable[[int], None] | None = None,
    ) -> commit_mod.CommitCounts:
        _ = (engine, session, rows, entity_name, account_name)
        assert on_write is not None
        on_write(1)
        raise commit_mod.ImportCommitError("synthetic partial failure")

    monkeypatch.setattr(commit_mod, "commit_session", fail_after_write)

    response = client.post(f"/imports/{created.json()['id']}/commit")

    assert response.status_code == 409
    assert response.json()["detail"] == "synthetic partial failure"
    assert (tmp_path / "refresh-state" / "pending").exists()


def test_nordnet_reupload_flags_duplicates(
    client: TestClient,
    nordnet_csv: Path,
    nordnet_accounts_yaml: Path,
) -> None:
    _ = nordnet_accounts_yaml
    first = upload(client, nordnet_csv)
    assert first.status_code == 201
    assert client.post(f"/imports/{first.json()['id']}/commit").status_code == 200

    second = upload(client, nordnet_csv)
    assert second.status_code == 201
    body = second.json()
    assert body["row_counts"]["warning"] == 2
    issues = [issue for row in body["rows"] for issue in row["issues"]]
    assert all(issue["code"] == "duplicate" for issue in issues)
    assert len(issues) == 2

    # Duplicates are idempotent upserts, so committing still works.
    assert client.post(f"/imports/{body['id']}/commit").status_code == 200


def test_nordnet_commit_without_accounts_config_conflicts(
    client: TestClient,
    nordnet_csv: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PENGE_NORDNET_ACCOUNTS_CONFIG", raising=False)
    created = upload(client, nordnet_csv)
    assert created.status_code == 201
    response = client.post(f"/imports/{created.json()['id']}/commit")
    assert response.status_code == 409
    assert "PENGE_NORDNET_ACCOUNTS_CONFIG" in response.json()["detail"]
    assert not (tmp_path / "refresh-state" / "pending").exists()


def test_nordnet_holdings_stage_patch_commit_and_repeat(
    client: TestClient,
    engine: Engine,
    nordnet_accounts_yaml: Path,
    tmp_path: Path,
) -> None:
    _ = nordnet_accounts_yaml
    history = write_nordnet_csv(
        tmp_path / "history.csv",
        [
            TXN_HEADER,
            txn_row(
                id_="TRADE",
                book_date="2026-05-01",
                depot=DEPOT,
                type_="KØBT",
                name="Synthetic Fund",
                isin="IE00B4L5Y983",
                amount="-10,00",
                saldo="90,00",
            ),
        ],
    )
    transaction_session = upload(client, history).json()
    assert client.post(f"/imports/{transaction_session['id']}/commit").status_code == 200
    path = write_nordnet_csv(
        tmp_path / f"Depotoversigt for kontonummer {DEPOT}, 7.5.2026.csv",
        [
            HLD_HEADER,
            hld_row(name="Synthetic Fund", currency="EUR", quantity="2", last_price="4,00"),
        ],
    )
    created = upload(client, path)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["source"] == "nordnet_holdings"
    assert body["params"] == {
        "account_number": DEPOT,
        "as_of": "2026-05-07",
        "empty_snapshot_confirmed": False,
    }
    assert body["rows"][0]["kind"] == "holding"
    row = body["rows"][0]
    invalid = client.patch(
        f"/imports/{body['id']}/rows/{row['id']}",
        json={"payload": {**row["payload"], "quantity": "invalid"}},
    )
    assert invalid.status_code == 200
    assert invalid.json()["status"] == "error"
    assert client.post(f"/imports/{body['id']}/commit").status_code == 409
    patched = client.patch(
        f"/imports/{body['id']}/rows/{row['id']}",
        json={"payload": {**row["payload"], "quantity": "3"}},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["payload"]["quantity"] == "3"
    assert (
        client.patch(f"/imports/{body['id']}/rows/{row['id']}", json={"excluded": True}).status_code
        == 200
    )
    assert client.post(f"/imports/{body['id']}/commit").status_code == 409
    assert (
        client.patch(
            f"/imports/{body['id']}/rows/{row['id']}", json={"excluded": False}
        ).status_code
        == 200
    )
    committed = client.post(f"/imports/{body['id']}/commit")
    assert committed.status_code == 200, committed.text
    assert committed.json()["counts"]["transactions"] == 0
    assert committed.json()["counts"]["holding_snapshots"] == 1
    repeated = upload(client, path).json()
    assert client.post(f"/imports/{repeated['id']}/commit").status_code == 200
    with engine.connect() as conn:
        security = conn.execute(
            text(
                "select hs.quantity from holding_snapshot hs "
                "join instrument i on i.id = hs.instrument_id "
                "where i.isin = 'IE00B4L5Y983' and hs.as_of = '2026-05-07'"
            )
        ).all()
        cash = conn.execute(
            text(
                "select count(*) from holding_snapshot hs "
                "join instrument i on i.id = hs.instrument_id where i.kind = 'cash'"
            )
        ).scalar_one()
    assert [r.quantity for r in security] == [2]
    assert cash == 1


def test_nordnet_holdings_unmapped_rolls_back_and_is_account_scoped(
    client: TestClient,
    engine: Engine,
    nordnet_accounts_yaml: Path,
    tmp_path: Path,
) -> None:
    _ = nordnet_accounts_yaml
    # A same-named instrument in a different account is not evidence for this account.
    with engine.begin() as conn:
        conn.execute(text("insert into entity (name, kind) values ('Other owner', 'person')"))
        conn.execute(
            text(
                "insert into account (entity_id, provider, external_id, name, kind, currency) "
                "select id, 'nordnet', '99999991', 'Other', 'aktiedepot', 'DKK' "
                "from entity where name = 'Other owner'"
            )
        )
        conn.execute(
            text(
                "insert into instrument (name, kind, currency, isin) "
                "values ('Synthetic Fund', 'security', 'EUR', 'IE00B4L5Y983')"
            )
        )
        conn.execute(
            text(
                "insert into holding_snapshot (account_id, instrument_id, as_of, quantity) "
                "select a.id, i.id, '2026-05-01', 1 from account a, instrument i "
                "where a.external_id = '99999991' and i.isin = 'IE00B4L5Y983'"
            )
        )
    path = write_nordnet_csv(
        tmp_path / f"Depotoversigt for kontonummer {DEPOT}, 7.5.2026.csv",
        [HLD_HEADER, hld_row(name="Synthetic Fund", currency="EUR", quantity="2")],
    )
    created = upload(client, path).json()
    response = client.post(f"/imports/{created['id']}/commit")
    assert response.status_code == 409
    assert "no ISIN mapping" in response.json()["detail"]
    with engine.connect() as conn:
        assert (
            conn.execute(
                text("select count(*) from holding_snapshot where as_of = '2026-05-07'")
            ).scalar_one()
            == 0
        )
        assert (
            conn.execute(
                text("select count(*) from account where external_id = :account"),
                {"account": DEPOT},
            ).scalar_one()
            == 0
        )


def test_nordnet_holdings_reject_unknown_account_and_date(
    client: TestClient,
    nordnet_accounts_yaml: Path,
    tmp_path: Path,
) -> None:
    _ = nordnet_accounts_yaml
    for filename in (
        "Depotoversigt for kontonummer 00000000, 7.5.2026.csv",
        f"Depotoversigt for kontonummer {DEPOT}, 32.5.2026.csv",
    ):
        path = write_nordnet_csv(
            tmp_path / filename,
            [HLD_HEADER, hld_row(name="Synthetic Fund", currency="EUR", quantity="2")],
        )
        assert upload(client, path).status_code == 422


def test_nordnet_empty_complete_snapshot_zeros_security_and_can_be_corrected(
    client: TestClient,
    engine: Engine,
    nordnet_accounts_yaml: Path,
    tmp_path: Path,
) -> None:
    _ = nordnet_accounts_yaml
    history = write_nordnet_csv(
        tmp_path / "history.csv",
        [
            TXN_HEADER,
            txn_row(
                id_="TRADE",
                book_date="2026-05-01",
                depot=DEPOT,
                type_="KØBT",
                name="Synthetic Fund",
                isin="IE00B4L5Y983",
                amount="-10,00",
                saldo="90,00",
            ),
        ],
    )
    created = upload(client, history).json()
    assert client.post(f"/imports/{created['id']}/commit").status_code == 200
    first = write_nordnet_csv(
        tmp_path / f"Depotoversigt for kontonummer {DEPOT}, 5.5.2026.csv",
        [
            HLD_HEADER,
            hld_row(
                name="Synthetic Fund",
                currency="EUR",
                quantity="2",
                value_dkk="100,00",
            ),
        ],
    )
    session = upload(client, first).json()
    assert client.post(f"/imports/{session['id']}/commit").status_code == 200

    empty = write_nordnet_csv(
        tmp_path / f"Depotoversigt for kontonummer {DEPOT}, 7.5.2026.csv",
        [HLD_HEADER],
    )
    session = upload(client, empty).json()
    assert session["source"] == "nordnet_holdings"
    assert session["row_counts"]["total"] == 0
    assert session["params"] == {
        "account_number": DEPOT,
        "as_of": "2026-05-07",
        "empty_snapshot_confirmed": True,
    }
    committed = client.post(f"/imports/{session['id']}/commit")
    assert committed.status_code == 200, committed.text
    assert committed.json()["counts"]["holding_snapshots"] == 1
    with engine.connect() as conn:
        position = conn.execute(
            text(
                "select hs.quantity, hs.market_value from holding_snapshot hs "
                "join instrument i on i.id = hs.instrument_id "
                "where i.isin = 'IE00B4L5Y983' and hs.as_of = '2026-05-07'"
            )
        ).one()
        cash = conn.execute(
            text(
                "select count(*) from holding_snapshot hs "
                "join instrument i on i.id = hs.instrument_id where i.kind = 'cash'"
            )
        ).scalar_one()
    assert position.quantity == 0
    assert position.market_value == 0
    assert cash == 1

    write_nordnet_csv(
        empty,
        [
            HLD_HEADER,
            hld_row(
                name="Synthetic Fund",
                currency="EUR",
                quantity="3",
                value_dkk="150,00",
            ),
        ],
    )
    correction = upload(client, empty).json()
    assert client.post(f"/imports/{correction['id']}/commit").status_code == 200
    with engine.connect() as conn:
        restored = conn.execute(
            text(
                "select hs.quantity from holding_snapshot hs "
                "join instrument i on i.id = hs.instrument_id "
                "where i.isin = 'IE00B4L5Y983' and hs.as_of = '2026-05-07'"
            )
        ).scalar_one()
    assert restored == 3


def test_nordnet_header_only_requires_validated_complete_export(
    client: TestClient,
    nordnet_accounts_yaml: Path,
    tmp_path: Path,
) -> None:
    _ = nordnet_accounts_yaml
    path = tmp_path / f"Depotoversigt for kontonummer {DEPOT}, 7.5.2026.csv"
    write_nordnet_csv(path, [("Navn", "Valuta", "Antal", *([""] * 7))])
    assert upload(client, path).status_code == 422

    write_nordnet_csv(path, [HLD_HEADER, hld_row(name="", currency="EUR", quantity="1")])
    assert upload(client, path).status_code == 422

    valid = write_nordnet_csv(path, [HLD_HEADER])
    staged = upload(client, valid).json()
    assert staged["params"]["empty_snapshot_confirmed"] is True
    stored_files = list((tmp_path / "imports").glob(f"*/{path.name}"))
    assert len(stored_files) == 1
    stored_files[0].write_bytes(b"changed after staging")
    committed = client.post(f"/imports/{staged['id']}/commit")
    assert committed.status_code == 409
    assert "changed since staging" in committed.json()["detail"]


def test_nordnet_header_only_requires_prior_security_in_same_account(
    client: TestClient,
    engine: Engine,
    nordnet_accounts_yaml: Path,
    tmp_path: Path,
) -> None:
    _ = nordnet_accounts_yaml
    with engine.begin() as conn:
        other_entity = conn.execute(
            text("insert into entity (name, kind) values ('Other owner', 'person') returning id")
        ).scalar_one()
        other_account = conn.execute(
            text(
                "insert into account (entity_id, provider, external_id, name, kind, currency) "
                "values (:owner, 'nordnet', '99999991', 'Other', 'aktiedepot', 'DKK') "
                "returning id"
            ),
            {"owner": other_entity},
        ).scalar_one()
        instrument = conn.execute(
            text(
                "insert into instrument (name, kind, currency, isin) "
                "values ('Synthetic Fund', 'security', 'EUR', 'IE00B4L5Y983') returning id"
            )
        ).scalar_one()
        conn.execute(
            text(
                "insert into holding_snapshot (account_id, instrument_id, as_of, quantity) "
                "values (:account, :instrument, '2026-05-01', 2)"
            ),
            {"account": other_account, "instrument": instrument},
        )

    empty = write_nordnet_csv(
        tmp_path / f"Depotoversigt for kontonummer {DEPOT}, 7.5.2026.csv",
        [HLD_HEADER],
    )
    staged = upload(client, empty).json()
    assert staged["params"]["empty_snapshot_confirmed"] is True
    response = client.post(f"/imports/{staged['id']}/commit")
    assert response.status_code == 409
    assert "prior mapped security snapshot" in response.json()["detail"]
    assert client.get(f"/imports/{staged['id']}").json()["status"] == "staged"
    assert not (tmp_path / "refresh-state" / "pending").exists()
    with engine.connect() as conn:
        assert (
            conn.execute(
                text(
                    "select count(*) from account where provider = 'nordnet' and external_id = :n"
                ),
                {"n": DEPOT},
            ).scalar_one()
            == 0
        )
        assert (
            conn.execute(
                text("select quantity from holding_snapshot where account_id = :account"),
                {"account": other_account},
            ).scalar_one()
            == 2
        )


# --------------------------------------------------------------------------- #
# Growney and PFA round-trips
# --------------------------------------------------------------------------- #


def test_growney_upload_commit_roundtrip(client: TestClient, engine: Engine) -> None:
    created = upload(client, GROWNEY_PDF, entity_name="Owner G")
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["source"] == "growney"
    kinds = {r["kind"] for r in body["rows"]}
    assert "transaction" in kinds
    assert "holding" in kinds
    assert body["params"]["depot_number"]

    committed = client.post(f"/imports/{body['id']}/commit")
    assert committed.status_code == 200, committed.text
    counts = committed.json()["counts"]
    assert counts["transactions"] > 0
    assert counts["holding_snapshots"] > 0

    with engine.connect() as conn:
        n_accounts = conn.execute(
            text("select count(*) from account where provider = 'growney'")
        ).scalar_one()
    assert n_accounts == 1


def test_pfa_upload_commit_roundtrip(client: TestClient, engine: Engine) -> None:
    created = upload(client, PFA_PDF, entity_name="Owner P")
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["source"] == "pfa"
    assert {r["kind"] for r in body["rows"]} == {"scheme"}
    assert body["params"]["policy_number"]

    committed = client.post(f"/imports/{body['id']}/commit")
    assert committed.status_code == 200, committed.text
    assert committed.json()["counts"]["holding_snapshots"] > 0

    with engine.connect() as conn:
        n_accounts = conn.execute(
            text("select count(*) from account where provider = 'pfa'")
        ).scalar_one()
    assert n_accounts > 0


def test_growney_commit_requires_entity_name(client: TestClient) -> None:
    created = upload(client, GROWNEY_PDF)
    assert created.status_code == 201
    response = client.post(f"/imports/{created.json()['id']}/commit")
    assert response.status_code == 409
    assert "entity_name" in response.json()["detail"]

    # Supplying it at commit time succeeds.
    response = client.post(
        f"/imports/{created.json()['id']}/commit",
        json={"entity_name": "Owner G"},
    )
    assert response.status_code == 200


# --------------------------------------------------------------------------- #
# Manual balances: error rows, PATCH corrections, exclusion
# --------------------------------------------------------------------------- #


def test_manual_balances_error_row_patch_and_commit(
    client: TestClient,
    engine: Engine,
    tmp_path: Path,
) -> None:
    path = manual_json(
        tmp_path,
        [
            {
                "entity": "Owner A",
                "account_name": "Cash DKK",
                "currency": "DKK",
                "as_of": "2026-06-01",
                "balance": "1234.50",
            },
            {
                "entity": "Owner A",
                "account_name": "Cash EUR",
                "currency": "NOT-A-CURRENCY",
                "as_of": "2026-06-01",
                "balance": "99.00",
            },
        ],
    )
    created = upload(client, path)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["source"] == "manual_balances"
    assert body["row_counts"]["error"] == 1

    # Committing with an error row is rejected.
    blocked = client.post(f"/imports/{body['id']}/commit")
    assert blocked.status_code == 409
    assert "error row" in blocked.json()["detail"]

    # PATCH the broken row; it revalidates to ok.
    error_row = next(r for r in body["rows"] if r["status"] == "error")
    fixed_payload = {**error_row["payload"], "currency": "EUR"}
    patched = client.patch(
        f"/imports/{body['id']}/rows/{error_row['id']}",
        json={"payload": fixed_payload},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["status"] == "ok"
    assert patched.json()["edited"] is True

    committed = client.post(f"/imports/{body['id']}/commit")
    assert committed.status_code == 200, committed.text
    assert committed.json()["counts"]["holding_snapshots"] == 2

    with engine.connect() as conn:
        n_snapshots = conn.execute(text("select count(*) from holding_snapshot")).scalar_one()
    assert n_snapshots == 2


def test_manual_balances_excluded_row_is_skipped(
    client: TestClient,
    engine: Engine,
    tmp_path: Path,
) -> None:
    path = manual_json(
        tmp_path,
        [
            {
                "entity": "Owner A",
                "account_name": "Cash DKK",
                "currency": "DKK",
                "as_of": "2026-06-01",
                "balance": "100.00",
            },
            {
                "entity": "Owner A",
                "account_name": "Cash EUR",
                "currency": "EUR",
                "as_of": "2026-06-01",
                "balance": "200.00",
            },
        ],
    )
    created = upload(client, path)
    body = created.json()
    second = body["rows"][1]
    patched = client.patch(
        f"/imports/{body['id']}/rows/{second['id']}",
        json={"excluded": True},
    )
    assert patched.status_code == 200
    assert patched.json()["excluded"] is True

    committed = client.post(f"/imports/{body['id']}/commit")
    assert committed.status_code == 200
    assert committed.json()["counts"]["holding_snapshots"] == 1

    with engine.connect() as conn:
        n_snapshots = conn.execute(text("select count(*) from holding_snapshot")).scalar_one()
    assert n_snapshots == 1


def test_patch_with_invalid_payload_marks_row_error(client: TestClient, tmp_path: Path) -> None:
    path = manual_json(
        tmp_path,
        [
            {
                "entity": "Owner A",
                "account_name": "Cash DKK",
                "currency": "DKK",
                "as_of": "2026-06-01",
                "balance": "100.00",
            }
        ],
    )
    body = upload(client, path).json()
    row = body["rows"][0]
    response = client.patch(
        f"/imports/{body['id']}/rows/{row['id']}",
        json={"payload": {**row["payload"], "balance": "-5"}},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "error"
    assert response.json()["issues"][0]["code"] == "invalid"


def test_patch_without_fields_is_rejected(client: TestClient, tmp_path: Path) -> None:
    path = manual_json(
        tmp_path,
        [
            {
                "entity": "Owner A",
                "account_name": "Cash",
                "currency": "EUR",
                "as_of": "2026-06-01",
                "balance": "1.00",
            }
        ],
    )
    body = upload(client, path).json()
    row = body["rows"][0]
    response = client.patch(f"/imports/{body['id']}/rows/{row['id']}", json={})
    assert response.status_code == 422


# --------------------------------------------------------------------------- #
# Lifecycle: list, discard, expiry, state guards
# --------------------------------------------------------------------------- #


def test_list_sessions(client: TestClient, tmp_path: Path) -> None:
    path = manual_json(
        tmp_path,
        [
            {
                "entity": "Owner A",
                "account_name": "Cash",
                "currency": "EUR",
                "as_of": "2026-06-01",
                "balance": "1.00",
            }
        ],
    )
    assert upload(client, path).status_code == 201
    listed = client.get("/imports")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["sessions"][0]["row_counts"]["total"] == 1


def test_discard_deletes_stored_file(client: TestClient, tmp_path: Path) -> None:
    path = manual_json(
        tmp_path,
        [
            {
                "entity": "Owner A",
                "account_name": "Cash",
                "currency": "EUR",
                "as_of": "2026-06-01",
                "balance": "1.00",
            }
        ],
    )
    body = upload(client, path).json()
    import_dir = tmp_path / "imports"
    assert any(import_dir.iterdir())

    discarded = client.delete(f"/imports/{body['id']}")
    assert discarded.status_code == 200
    assert discarded.json()["status"] == "discarded"
    assert not any(import_dir.iterdir())

    # Discard is idempotent; commit afterwards is a state conflict.
    assert client.delete(f"/imports/{body['id']}").status_code == 200
    assert client.post(f"/imports/{body['id']}/commit").status_code == 409


def test_committed_sessions_cannot_be_discarded_or_patched(
    client: TestClient,
    tmp_path: Path,
) -> None:
    path = manual_json(
        tmp_path,
        [
            {
                "entity": "Owner A",
                "account_name": "Cash",
                "currency": "EUR",
                "as_of": "2026-06-01",
                "balance": "1.00",
            }
        ],
    )
    body = upload(client, path).json()
    assert client.post(f"/imports/{body['id']}/commit").status_code == 200

    assert client.delete(f"/imports/{body['id']}").status_code == 409
    row = body["rows"][0]
    response = client.patch(
        f"/imports/{body['id']}/rows/{row['id']}",
        json={"excluded": True},
    )
    assert response.status_code == 409


def test_expired_session_rejects_commit(
    client: TestClient,
    engine: Engine,
    tmp_path: Path,
) -> None:
    path = manual_json(
        tmp_path,
        [
            {
                "entity": "Owner A",
                "account_name": "Cash",
                "currency": "EUR",
                "as_of": "2026-06-01",
                "balance": "1.00",
            }
        ],
    )
    body = upload(client, path).json()
    with engine.begin() as conn:
        conn.execute(
            text("update import_session set expires_at = now() - interval '1 day' where id = :id"),
            {"id": body["id"]},
        )

    fetched = client.get(f"/imports/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "expired"
    assert client.post(f"/imports/{body['id']}/commit").status_code == 409


# --------------------------------------------------------------------------- #
# Upload validation
# --------------------------------------------------------------------------- #


def test_unknown_session_is_404(client: TestClient) -> None:
    response = client.get(f"/imports/{uuid.uuid4()}")
    assert response.status_code == 404


def test_unknown_source_is_rejected(client: TestClient, tmp_path: Path) -> None:
    path = tmp_path / "statement.csv"
    path.write_text("a,b,c", encoding="utf-8")
    response = upload(client, path, source="not_a_source")
    assert response.status_code == 422


def test_undetectable_file_is_rejected(client: TestClient, tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("plain text, no statement", encoding="utf-8")
    response = upload(client, path)
    assert response.status_code == 422
    assert "could not detect" in response.json()["detail"]


def test_oversize_upload_is_rejected(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PENGE_IMPORT_MAX_BYTES", "64")
    path = tmp_path / "big.json"
    path.write_text(json.dumps({"balances": [{"entity": "x" * 200}]}), encoding="utf-8")
    response = upload(client, path, source="manual_balances")
    assert response.status_code == 413
    # The partial upload is cleaned up.
    import_dir = tmp_path / "imports"
    assert not any(import_dir.iterdir())


# --------------------------------------------------------------------------- #
# Mapping patches (AI review layer, issue #210)
# --------------------------------------------------------------------------- #

_BALANCE: dict[str, object] = {
    "entity": "Owner A",
    "account_name": "Cash DKK",
    "currency": "DKK",
    "as_of": "2026-06-01",
    "balance": "100.00",
}


def test_patch_mappings_manual_sets_no_provenance(client: TestClient, tmp_path: Path) -> None:
    body = upload(client, manual_json(tmp_path, [_BALANCE])).json()
    row = body["rows"][0]
    assert row["mappings"] == {}
    assert row["suggested_by"] is None
    assert row["accepted_at"] is None

    patched = client.patch(
        f"/imports/{body['id']}/rows/{row['id']}",
        json={"mappings": {"category": "cash buffer"}},
    )
    assert patched.status_code == 200, patched.text
    out = patched.json()
    assert out["mappings"] == {"category": "cash buffer"}
    assert out["suggested_by"] is None
    assert out["accepted_at"] is None
    # Mappings live next to the payload, never inside it.
    assert "category" not in out["payload"]
    assert out["edited"] is False


def test_patch_mappings_with_suggested_by_stamps_acceptance(
    client: TestClient, tmp_path: Path
) -> None:
    body = upload(client, manual_json(tmp_path, [_BALANCE])).json()
    row = body["rows"][0]
    patched = client.patch(
        f"/imports/{body['id']}/rows/{row['id']}",
        json={
            "mappings": {"category": "cash buffer", "asset_class": "cash"},
            "suggested_by": "suggest_import_mapping",
        },
    )
    assert patched.status_code == 200, patched.text
    out = patched.json()
    assert out["mappings"] == {"category": "cash buffer", "asset_class": "cash"}
    assert out["suggested_by"] == "suggest_import_mapping"
    assert out["accepted_at"] is not None

    # Re-mapping manually afterwards clears the AI provenance.
    repatched = client.patch(
        f"/imports/{body['id']}/rows/{row['id']}",
        json={"mappings": {"category": "household"}},
    )
    assert repatched.status_code == 200
    out = repatched.json()
    assert out["mappings"] == {"category": "household"}
    assert out["suggested_by"] is None
    assert out["accepted_at"] is None


def test_patch_mappings_persist_across_get(client: TestClient, tmp_path: Path) -> None:
    body = upload(client, manual_json(tmp_path, [_BALANCE])).json()
    row = body["rows"][0]
    client.patch(
        f"/imports/{body['id']}/rows/{row['id']}",
        json={
            "mappings": {"counterparty": "Employer A/S"},
            "suggested_by": "suggest_import_mapping",
        },
    )
    fetched = client.get(f"/imports/{body['id']}").json()
    out = fetched["rows"][0]
    assert out["mappings"] == {"counterparty": "Employer A/S"}
    assert out["suggested_by"] == "suggest_import_mapping"


def test_patch_mappings_unknown_field_is_rejected(client: TestClient, tmp_path: Path) -> None:
    body = upload(client, manual_json(tmp_path, [_BALANCE])).json()
    row = body["rows"][0]
    response = client.patch(
        f"/imports/{body['id']}/rows/{row['id']}",
        json={"mappings": {"colour": "blue"}},
    )
    assert response.status_code == 422
    assert "unknown mapping fields: colour" in response.json()["detail"]


def test_patch_mappings_empty_value_is_rejected(client: TestClient, tmp_path: Path) -> None:
    body = upload(client, manual_json(tmp_path, [_BALANCE])).json()
    row = body["rows"][0]
    response = client.patch(
        f"/imports/{body['id']}/rows/{row['id']}",
        json={"mappings": {"category": "   "}},
    )
    assert response.status_code == 422
    assert "non-empty" in response.json()["detail"]


def test_patch_mappings_oversize_value_is_rejected(client: TestClient, tmp_path: Path) -> None:
    body = upload(client, manual_json(tmp_path, [_BALANCE])).json()
    row = body["rows"][0]
    response = client.patch(
        f"/imports/{body['id']}/rows/{row['id']}",
        json={"mappings": {"category": "x" * 501}},
    )
    assert response.status_code == 422
    assert "exceeds 500" in response.json()["detail"]


def test_patch_suggested_by_without_mappings_is_rejected(
    client: TestClient, tmp_path: Path
) -> None:
    body = upload(client, manual_json(tmp_path, [_BALANCE])).json()
    row = body["rows"][0]
    for payload in (
        {"suggested_by": "suggest_import_mapping"},
        {"mappings": {}, "suggested_by": "suggest_import_mapping"},
    ):
        response = client.patch(f"/imports/{body['id']}/rows/{row['id']}", json=payload)
        assert response.status_code == 422
        assert "non-empty mappings" in response.json()["detail"]


def test_patch_blank_suggested_by_is_rejected(client: TestClient, tmp_path: Path) -> None:
    body = upload(client, manual_json(tmp_path, [_BALANCE])).json()
    row = body["rows"][0]
    response = client.patch(
        f"/imports/{body['id']}/rows/{row['id']}",
        json={"mappings": {"category": "cash buffer"}, "suggested_by": "   "},
    )
    assert response.status_code == 422
    assert "non-blank" in response.json()["detail"]

    oversize = client.patch(
        f"/imports/{body['id']}/rows/{row['id']}",
        json={"mappings": {"category": "cash buffer"}, "suggested_by": "x" * 201},
    )
    assert oversize.status_code == 422
    assert "exceeds 200" in oversize.json()["detail"]


def test_patch_empty_mappings_clears_mappings_and_provenance(
    client: TestClient, tmp_path: Path
) -> None:
    body = upload(client, manual_json(tmp_path, [_BALANCE])).json()
    row = body["rows"][0]
    accepted = client.patch(
        f"/imports/{body['id']}/rows/{row['id']}",
        json={"mappings": {"category": "cash buffer"}, "suggested_by": "suggest_import_mapping"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["accepted_at"] is not None

    cleared = client.patch(f"/imports/{body['id']}/rows/{row['id']}", json={"mappings": {}})
    assert cleared.status_code == 200
    out = cleared.json()
    assert out["mappings"] == {}
    assert out["suggested_by"] is None
    assert out["accepted_at"] is None
