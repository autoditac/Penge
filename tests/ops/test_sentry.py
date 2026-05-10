"""Tests for :mod:`penge.ops.sentry`.

Covers:

* :func:`init_sentry` is a no-op when ``SENTRY_DSN`` is unset.
* :func:`init_sentry` is idempotent (multiple calls do not double-init).
* The :func:`before_send` hook redacts PII keys recursively, mirroring
  the regex used by the MCP audit logger (``apps/mcp/src/audit.ts``).
"""

from __future__ import annotations

from typing import Any

import pytest

from penge.ops import sentry as sentry_mod
from penge.ops.sentry import ENV_DSN, REDACTED, before_send, init_sentry


@pytest.fixture(autouse=True)
def _reset_sentry_state() -> None:
    sentry_mod._reset_for_tests()


def test_init_noop_when_dsn_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_DSN, raising=False)
    assert init_sentry() is False
    # And again — still a no-op.
    assert init_sentry() is False


def test_init_noop_when_dsn_blank(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_DSN, "   ")
    assert init_sentry() is False


def test_init_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Initialising twice with a DSN must only call sentry_sdk.init once."""
    calls: list[dict[str, Any]] = []

    class _FakeSDK:
        @staticmethod
        def init(**kwargs: Any) -> None:
            calls.append(kwargs)

        @staticmethod
        def set_tag(*_args: Any, **_kwargs: Any) -> None:
            return None

    monkeypatch.setitem(__import__("sys").modules, "sentry_sdk", _FakeSDK)
    monkeypatch.setenv(ENV_DSN, "https://public@sentry.example.invalid/1")

    assert init_sentry(component="vault-watcher") is True
    assert init_sentry(component="vault-watcher") is False
    assert len(calls) == 1
    # before_send wired in
    assert calls[0]["before_send"] is before_send
    assert calls[0]["send_default_pii"] is False


def test_init_uses_env_for_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class _FakeSDK:
        @staticmethod
        def init(**kwargs: Any) -> None:
            captured.update(kwargs)

        @staticmethod
        def set_tag(*_args: Any, **_kwargs: Any) -> None:
            return None

    monkeypatch.setitem(__import__("sys").modules, "sentry_sdk", _FakeSDK)
    monkeypatch.setenv(ENV_DSN, "https://public@sentry.example.invalid/1")
    monkeypatch.delenv("SENTRY_ENVIRONMENT", raising=False)
    monkeypatch.setenv("PENGE_ENV", "prod")

    assert init_sentry() is True
    assert captured["environment"] == "prod"


def test_before_send_redacts_top_level_keys() -> None:
    event = {
        "extra": {
            "iban": "DE00 1234 5678 9012 3456 78",
            "account": "123-456",
            "tax_id": "1234567890",
            "tax-id": "alt-form",
            "cpr": "010199-1234",
            "name": "Rouven Sacha",
            "email": "user@example.com",
            "safe": "ok",
        }
    }
    redacted = before_send(dict(event), {})
    extra = redacted["extra"]
    for key in ("iban", "account", "tax_id", "tax-id", "cpr", "name", "email"):
        assert extra[key] == REDACTED, key
    assert extra["safe"] == "ok"


def test_before_send_redacts_nested_and_lists() -> None:
    event = {
        "breadcrumbs": [
            {"data": {"iban": "DE000", "amount": 42}},
            {"data": {"holder_name": "Spouse", "currency": "EUR"}},
        ],
        "tags": {"username_email": "x@y.z", "ok": "v"},
    }
    redacted = before_send(dict(event), {})
    bc = redacted["breadcrumbs"]
    assert bc[0]["data"]["iban"] == REDACTED
    assert bc[0]["data"]["amount"] == 42
    # `holder_name` matches `name`
    assert bc[1]["data"]["holder_name"] == REDACTED
    assert bc[1]["data"]["currency"] == "EUR"
    # `username_email` matches `email`
    assert redacted["tags"]["username_email"] == REDACTED
    assert redacted["tags"]["ok"] == "v"


def test_before_send_preserves_primitives() -> None:
    event = {"level": "error", "message": "boom"}
    assert before_send(dict(event), {}) == event


def test_before_send_handles_tuples() -> None:
    event = {"contexts": {"runtime": {"versions": ("3.12", "win")}, "iban": "DE000"}}
    redacted = before_send(dict(event), {})
    assert redacted["contexts"]["iban"] == REDACTED
    assert redacted["contexts"]["runtime"]["versions"] == ("3.12", "win")
