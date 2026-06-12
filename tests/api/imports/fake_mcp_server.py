"""Fake MCP stdio server for bridge tests.

Speaks just enough newline-delimited JSON-RPC for
``penge.api.imports.mcp_bridge``: answers ``initialize``, swallows
``notifications/initialized``, and answers ``tools/call`` according to
``FAKE_MCP_MODE``:

- ``success`` (default) — structured suggestion payload echoing the
  ``import_session_id`` argument.
- ``text_only`` — same payload but only as a JSON text content block
  (no ``structuredContent``).
- ``tool_error`` — ``isError: true`` with an explanatory text block.
- ``rpc_error`` — JSON-RPC level error response.
- ``hang`` — never answers the tool call (bridge timeout path).
- ``garbage`` — writes a non-JSON line.

Run directly via ``python fake_mcp_server.py``; only stdlib is used so
the subprocess needs no project environment.
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any


def _payload(session_id: str) -> dict[str, Any]:
    return {
        "session": {
            "id": session_id,
            "source": "nordnet",
            "status": "staged",
            "rows_considered": 2,
        },
        "suggestions": [
            {
                "row_id": "11111111-1111-1111-1111-111111111111",
                "row_index": 0,
                "kind": "transaction",
                "field": "category",
                "value": "deposit",
                "confidence": 0.9,
                "reason": "canonical transaction kind",
            }
        ],
    }


def _respond(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def main() -> None:
    mode = os.environ.get("FAKE_MCP_MODE", "success")
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        request = json.loads(line)
        method = request.get("method")
        if method == "initialize":
            _respond(
                {
                    "jsonrpc": "2.0",
                    "id": request["id"],
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "fake-mcp", "version": "0"},
                    },
                }
            )
        elif method == "notifications/initialized":
            continue
        elif method == "tools/call":
            if mode == "hang":
                time.sleep(120)
                return
            if mode == "garbage":
                sys.stdout.write("this is not json\n")
                sys.stdout.flush()
                return
            if mode == "rpc_error":
                _respond(
                    {
                        "jsonrpc": "2.0",
                        "id": request["id"],
                        "error": {"code": -32602, "message": "bad params from fake server"},
                    }
                )
                return
            if mode == "tool_error":
                _respond(
                    {
                        "jsonrpc": "2.0",
                        "id": request["id"],
                        "result": {
                            "content": [{"type": "text", "text": "session is not staged"}],
                            "isError": True,
                        },
                    }
                )
                return
            session_id = request["params"]["arguments"].get(
                "import_session_id", "00000000-0000-0000-0000-000000000000"
            )
            payload = _payload(session_id)
            result: dict[str, Any] = {"content": [{"type": "text", "text": json.dumps(payload)}]}
            if mode != "text_only":
                result["structuredContent"] = payload
            _respond({"jsonrpc": "2.0", "id": request["id"], "result": result})
            return
        else:
            continue


if __name__ == "__main__":
    main()
