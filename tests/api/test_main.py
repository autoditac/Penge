"""CLI entrypoint contract: flags map deterministically onto uvicorn."""

from __future__ import annotations

from typing import Any

import pytest
import uvicorn

from penge.api import __main__ as api_main


def _run_main(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def fake_run(app: str, **kwargs: Any) -> None:
        captured["app"] = app
        captured.update(kwargs)

    # __main__ calls uvicorn.run via the module attribute, so patching the
    # uvicorn module itself intercepts the call without re-exporting it.
    monkeypatch.setattr(uvicorn, "run", fake_run)
    monkeypatch.setattr("sys.argv", ["penge-api", *argv])
    api_main.main()
    return captured


def test_verbose_switches_uvicorn_to_debug(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _run_main(monkeypatch, ["--verbose"])
    assert captured["log_level"] == "debug"


def test_default_log_level_is_info(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _run_main(monkeypatch, [])
    assert captured["log_level"] == "info"
    assert captured["app"] == "penge.api.app:create_app"
    assert captured["factory"] is True
