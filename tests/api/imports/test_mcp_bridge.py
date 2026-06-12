"""Unit tests for the MCP stdio bridge against a stdlib fake server.

No database and no real MCP server: ``fake_mcp_server.py`` speaks the
newline-delimited JSON-RPC subset the bridge uses, with failure modes
selected via ``FAKE_MCP_MODE``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from penge.api.imports import mcp_bridge

FAKE_SERVER = Path(__file__).parent / "fake_mcp_server.py"


def _command(mode: str, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    monkeypatch.setenv("FAKE_MCP_MODE", mode)
    return [sys.executable, str(FAKE_SERVER)]


def _session_id(result: dict[str, object]) -> object:
    session = result["session"]
    assert isinstance(session, dict)
    return session["id"]


def test_success_returns_structured_content(monkeypatch: pytest.MonkeyPatch) -> None:
    result = mcp_bridge.call_tool(
        _command("success", monkeypatch),
        tool="suggest_import_mapping",
        arguments={"import_session_id": "abc-123"},
        timeout_seconds=10,
    )
    assert _session_id(result) == "abc-123"
    suggestions = result["suggestions"]
    assert isinstance(suggestions, list)
    assert len(suggestions) == 1


def test_text_only_result_falls_back_to_json_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = mcp_bridge.call_tool(
        _command("text_only", monkeypatch),
        tool="suggest_import_mapping",
        arguments={"import_session_id": "abc-456"},
        timeout_seconds=10,
    )
    assert _session_id(result) == "abc-456"


def test_tool_error_raises_tool_error(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(mcp_bridge.McpToolError, match="session is not staged"):
        mcp_bridge.call_tool(
            _command("tool_error", monkeypatch),
            tool="suggest_import_mapping",
            arguments={"import_session_id": "abc"},
            timeout_seconds=10,
        )


def test_rpc_error_raises_tool_error(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(mcp_bridge.McpToolError, match="bad params"):
        mcp_bridge.call_tool(
            _command("rpc_error", monkeypatch),
            tool="suggest_import_mapping",
            arguments={"import_session_id": "abc"},
            timeout_seconds=10,
        )


def test_hang_times_out_as_bridge_error(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(mcp_bridge.McpBridgeError, match="did not answer within"):
        mcp_bridge.call_tool(
            _command("hang", monkeypatch),
            tool="suggest_import_mapping",
            arguments={"import_session_id": "abc"},
            timeout_seconds=1,
        )


def test_garbage_output_is_a_bridge_error(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(mcp_bridge.McpBridgeError, match="non-JSON line"):
        mcp_bridge.call_tool(
            _command("garbage", monkeypatch),
            tool="suggest_import_mapping",
            arguments={"import_session_id": "abc"},
            timeout_seconds=10,
        )


def test_missing_binary_is_a_bridge_error() -> None:
    with pytest.raises(mcp_bridge.McpBridgeError, match="could not start"):
        mcp_bridge.call_tool(
            ["/nonexistent/penge-mcp-server"],
            tool="suggest_import_mapping",
            arguments={},
            timeout_seconds=5,
        )
