"""Tests for :func:`penge.ops.heartbeat.heartbeat`.

The helper must:

* No-op when ``PENGE_UPTIME_KUMA_PUSH_URL`` is unset.
* Build the URL as ``<prefix>/<slug>`` with the slug URL-encoded.
* Pass ``status``, ``msg``, and ``ping`` query parameters.
* Swallow network errors (Uptime Kuma's stale-heartbeat alert is the
  source of truth — a failed ping must not break ingestion).
* Reject empty slugs at the API boundary.
"""

from __future__ import annotations

import logging

import httpx
import pytest

from penge.ops.heartbeat import ENV_PUSH_URL, heartbeat


def _client_with(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler)


def test_noop_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_PUSH_URL, raising=False)
    calls: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    with _client_with(transport) as client:
        heartbeat("any-slug", client=client)
    assert calls == []


def test_noop_when_env_blank(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_PUSH_URL, "   ")
    calls: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    with _client_with(transport) as client:
        heartbeat("slug", client=client)
    assert calls == []


def test_sends_get_with_expected_query(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_PUSH_URL, "https://uptime.example.invalid/api/push")
    captured: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(req)
        return httpx.Response(200, text="OK")

    transport = httpx.MockTransport(handler)
    with _client_with(transport) as client:
        heartbeat("tok123", status="up", message="ok", client=client)

    assert len(captured) == 1
    req = captured[0]
    assert req.method == "GET"
    assert req.url.path == "/api/push/tok123"
    assert req.url.params["status"] == "up"
    assert req.url.params["msg"] == "ok"
    assert "ping" in req.url.params


def test_strips_trailing_slash_in_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_PUSH_URL, "https://uptime.example.invalid/api/push/")
    captured: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(req)
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    with _client_with(transport) as client:
        heartbeat("tok", client=client)

    assert captured[0].url.path == "/api/push/tok"


def test_url_encodes_slug(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_PUSH_URL, "https://uptime.example.invalid/api/push")
    captured: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(req)
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    with _client_with(transport) as client:
        heartbeat("a/b c", client=client)

    # httpx normalises the path; the encoded form must contain %2F and %20.
    raw_path = str(captured[0].url)
    assert "a%2Fb%20c" in raw_path


def test_swallows_http_error(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv(ENV_PUSH_URL, "https://uptime.example.invalid/api/push")

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="kuma-down")

    transport = httpx.MockTransport(handler)
    with _client_with(transport) as client, caplog.at_level(logging.WARNING, "penge.ops.heartbeat"):
        heartbeat("tok", client=client)

    assert any("heartbeat failed" in rec.message for rec in caplog.records)


def test_swallows_transport_error(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv(ENV_PUSH_URL, "https://uptime.example.invalid/api/push")

    def handler(_req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("kuma unreachable")

    transport = httpx.MockTransport(handler)
    with _client_with(transport) as client, caplog.at_level(logging.WARNING, "penge.ops.heartbeat"):
        heartbeat("tok", client=client)

    assert any("heartbeat failed" in rec.message for rec in caplog.records)


def test_rejects_empty_slug(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_PUSH_URL, "https://uptime.example.invalid/api/push")
    with pytest.raises(ValueError, match="non-empty slug"):
        heartbeat("")
