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

from tests.api.imports.conftest import DB_URL, REPO_ROOT, manual_json, upload
from tests.ingest.nordnet._fixture_builders import TXN_HEADER, txn_row, write_nordnet_csv

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from sqlalchemy.engine import Engine

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

    with engine.connect() as conn:
        n_txns = conn.execute(text('select count(*) from "transaction"')).scalar_one()
    assert n_txns == 2


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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PENGE_NORDNET_ACCOUNTS_CONFIG", raising=False)
    created = upload(client, nordnet_csv)
    assert created.status_code == 201
    response = client.post(f"/imports/{created.json()['id']}/commit")
    assert response.status_code == 409
    assert "PENGE_NORDNET_ACCOUNTS_CONFIG" in response.json()["detail"]


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
    response = client.patch(
        f"/imports/{body['id']}/rows/{row['id']}",
        json={"suggested_by": "suggest_import_mapping"},
    )
    assert response.status_code == 422
    assert "only valid together with mappings" in response.json()["detail"]
