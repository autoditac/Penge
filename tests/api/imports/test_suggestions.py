"""Tests for the MCP-backed suggestions endpoint against a real Postgres.

Uses the shared conftest harness plus ``fake_mcp_server.py`` as the
configured MCP command, so no Node toolchain is needed. All fixture
data is synthetic.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tests.api.imports.conftest import DB_URL, manual_json, upload
from tests.ingest.nordnet._fixture_builders import HLD_HEADER, hld_row, write_nordnet_csv

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(
    DB_URL is None,
    reason="set PENGE_TEST_DATABASE_URL or DATABASE_URL to run import-API tests",
)

FAKE_SERVER = Path(__file__).parent / "fake_mcp_server.py"

_BALANCE: dict[str, object] = {
    "entity": "Owner A",
    "account_name": "Cash DKK",
    "currency": "DKK",
    "as_of": "2026-06-01",
    "balance": "100.00",
}


def _configure_fake(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    monkeypatch.setenv("PENGE_MCP_SUGGEST_COMMAND", f"{sys.executable} {FAKE_SERVER}")
    monkeypatch.setenv("FAKE_MCP_MODE", mode)


def test_suggestions_unconfigured_returns_503(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PENGE_MCP_SUGGEST_COMMAND", raising=False)
    body = upload(client, manual_json(tmp_path, [_BALANCE])).json()
    response = client.post(f"/imports/{body['id']}/suggestions")
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_suggestions_proxy_success(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_fake(monkeypatch, "success")
    body = upload(client, manual_json(tmp_path, [_BALANCE])).json()
    response = client.post(f"/imports/{body['id']}/suggestions")
    assert response.status_code == 200, response.text
    out = response.json()
    assert out["suggested_by"] == "suggest_import_mapping"
    # The fake server echoes the session id it was asked about.
    assert out["session"]["id"] == body["id"]
    assert out["session"]["rows_considered"] == 2
    assert len(out["suggestions"]) == 1
    suggestion = out["suggestions"][0]
    assert suggestion["field"] == "category"
    assert suggestion["value"] == "deposit"
    assert suggestion["confidence"] == 0.9


def test_nordnet_holdings_suggestions_do_not_fail(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    accounts = tmp_path / "accounts.yaml"
    accounts.write_text(
        'accounts:\n  - number: "99999990"\n    entity: "Owner A"\n    kind: aktiedepot\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("PENGE_NORDNET_ACCOUNTS_CONFIG", str(accounts))
    _configure_fake(monkeypatch, "success")
    path = write_nordnet_csv(
        tmp_path / "Depotoversigt for kontonummer 99999990, 7.5.2026.csv",
        [HLD_HEADER, hld_row(name="Synthetic World ETF", currency="EUR", quantity="2")],
    )
    created = upload(client, path)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["source"] == "nordnet_holdings"
    assert body["params"] == {
        "account_number": "99999990",
        "as_of": "2026-05-07",
        "empty_snapshot_confirmed": False,
    }
    assert body["rows"][0]["kind"] == "holding"
    assert body["rows"][0]["payload"]["name"] == "Synthetic World ETF"
    assert body["rows"][0]["payload"]["quantity"] == "2"
    assert "market_value_dkk" in body["rows"][0]["payload"]

    response = client.post(f"/imports/{body['id']}/suggestions")
    assert response.status_code == 200, response.text
    assert response.json()["session"]["id"] == body["id"]


def test_suggestions_tool_error_returns_502(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_fake(monkeypatch, "tool_error")
    body = upload(client, manual_json(tmp_path, [_BALANCE])).json()
    response = client.post(f"/imports/{body['id']}/suggestions")
    assert response.status_code == 502
    assert "session is not staged" in response.json()["detail"]


def test_suggestions_unreachable_server_returns_503(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PENGE_MCP_SUGGEST_COMMAND", "/nonexistent/penge-mcp-server")
    body = upload(client, manual_json(tmp_path, [_BALANCE])).json()
    response = client.post(f"/imports/{body['id']}/suggestions")
    assert response.status_code == 503
    assert "unreachable" in response.json()["detail"]


def test_suggestions_timeout_returns_503(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_fake(monkeypatch, "hang")
    monkeypatch.setenv("PENGE_MCP_SUGGEST_TIMEOUT_SECONDS", "1")
    body = upload(client, manual_json(tmp_path, [_BALANCE])).json()
    response = client.post(f"/imports/{body['id']}/suggestions")
    assert response.status_code == 503
    assert "unreachable" in response.json()["detail"]


def test_suggestions_unknown_session_returns_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_fake(monkeypatch, "success")
    response = client.post(f"/imports/{uuid.uuid4()}/suggestions")
    assert response.status_code == 404


def test_suggestions_on_discarded_session_returns_409(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_fake(monkeypatch, "success")
    body = upload(client, manual_json(tmp_path, [_BALANCE])).json()
    assert client.delete(f"/imports/{body['id']}").status_code == 200
    response = client.post(f"/imports/{body['id']}/suggestions")
    assert response.status_code == 409
