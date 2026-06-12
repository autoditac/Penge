"""Minimal MCP stdio client for the suggestion bridge (ADR-0038).

The FastAPI app never embeds suggestion logic: the deterministic rules
live in the MCP tool ``suggest_import_mapping`` (apps/mcp), and this
module is the only way the API reaches them. It spawns the configured
MCP server command, speaks newline-delimited JSON-RPC over stdio
(initialize → notifications/initialized → tools/call), and returns the
tool's structured output.

The bridge is deliberately tiny and synchronous: one subprocess per
call, a hard wall-clock deadline, and no connection reuse. Suggestion
requests are a manual wizard action, not a hot path.
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
from typing import IO, TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

log = logging.getLogger("penge.api.imports")

_PROTOCOL_VERSION = "2024-11-05"
_CLIENT_INFO = {"name": "penge-api", "version": "0"}
_STDERR_CAP_BYTES = 16_384


class McpBridgeError(Exception):
    """The MCP server could not be reached or did not answer in time."""


class McpToolError(Exception):
    """The MCP server answered, but the tool call itself failed."""


def _drain_stderr(stream: IO[bytes], sink: list[bytes]) -> None:
    """Accumulate up to ``_STDERR_CAP_BYTES`` of stderr for diagnostics."""
    captured = 0
    for line in stream:
        if captured < _STDERR_CAP_BYTES:
            sink.append(line[: _STDERR_CAP_BYTES - captured])
            captured += len(line)


def _write_message(stdin: IO[bytes], message: dict[str, object]) -> None:
    stdin.write(json.dumps(message).encode("utf-8") + b"\n")
    stdin.flush()


def _read_response(stdout: IO[bytes], expected_id: int) -> dict[str, object]:
    """Read newline-delimited JSON until the response for ``expected_id``.

    Server-initiated requests/notifications (logging, progress) are
    skipped. EOF before the response is a bridge error.
    """
    for raw in stdout:
        line = raw.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            raise McpBridgeError(f"MCP server wrote a non-JSON line: {line[:200]!r}") from exc
        if not isinstance(message, dict) or message.get("id") != expected_id:
            continue
        if "error" in message:
            error = message["error"]
            detail = error.get("message", str(error)) if isinstance(error, dict) else str(error)
            raise McpToolError(f"MCP request failed: {detail}")
        result = message.get("result")
        if not isinstance(result, dict):
            raise McpBridgeError("MCP response carried no result object")
        return result
    raise McpBridgeError("MCP server closed the stream before answering")


def _extract_structured(result: dict[str, object]) -> dict[str, object]:
    """Pull the tool's structured output from a ``tools/call`` result."""
    raw_content = result.get("content")
    content = raw_content if isinstance(raw_content, list) else []
    if result.get("isError"):
        texts = [
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        raise McpToolError("; ".join(t for t in texts if t) or "tool reported an error")
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            try:
                parsed = json.loads(str(item.get("text", "")))
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
    raise McpBridgeError("tool result carried no structured content")


def call_tool(
    command: Sequence[str],
    *,
    tool: str,
    arguments: dict[str, object],
    timeout_seconds: float,
) -> dict[str, object]:
    """Run one MCP tool call against a freshly spawned stdio server.

    Raises :class:`McpBridgeError` when the server cannot be spawned,
    times out, or violates the protocol; :class:`McpToolError` when the
    server works but the tool call fails (bad session state etc.).
    """
    try:
        process = subprocess.Popen(  # noqa: S603 — command comes from trusted env config
            list(command),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise McpBridgeError(f"could not start MCP server {command[0]!r}: {exc}") from exc

    if process.stdin is None or process.stdout is None or process.stderr is None:
        process.kill()
        raise McpBridgeError("MCP server pipes were not created")

    stderr_sink: list[bytes] = []
    threading.Thread(target=_drain_stderr, args=(process.stderr, stderr_sink), daemon=True).start()

    timer = threading.Timer(timeout_seconds, process.kill)
    timer.start()
    try:
        _write_message(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": _PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": _CLIENT_INFO,
                },
            },
        )
        _read_response(process.stdout, 1)
        _write_message(process.stdin, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        _write_message(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": tool, "arguments": arguments},
            },
        )
        result = _read_response(process.stdout, 2)
        return _extract_structured(result)
    except BrokenPipeError as exc:
        raise McpBridgeError("MCP server exited before the call completed") from exc
    except McpBridgeError:
        if not timer.is_alive():  # the watchdog fired: report the timeout, not the symptom
            raise McpBridgeError(f"MCP server did not answer within {timeout_seconds:g}s") from None
        raise
    finally:
        timer.cancel()
        process.stdin.close()
        process.kill()
        process.wait(timeout=5)
        if process.returncode not in (0, -9) and stderr_sink:
            log.debug(
                "MCP server stderr (exit=%s): %s",
                process.returncode,
                b"".join(stderr_sink).decode("utf-8", errors="replace")[:2000],
            )
