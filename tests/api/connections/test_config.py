"""Unit tests for connection feature configuration (no DB)."""

from __future__ import annotations

from pathlib import Path

from penge.api.connections.config import DEFAULT_REDIRECT_URL, ConnectionsConfig


def test_disabled_without_key() -> None:
    config = ConnectionsConfig.from_env({})
    assert config.enabled is False
    assert config.redirect_url == DEFAULT_REDIRECT_URL


def test_enabled_when_key_present(tmp_path: Path) -> None:
    key = tmp_path / "app.pem"
    key.write_text("key-material-placeholder\n", encoding="utf-8")
    config = ConnectionsConfig.from_env(
        {
            "ENABLEBANKING_APPLICATION_ID": "app-1",
            "ENABLEBANKING_KEY_PATH": str(key),
        }
    )
    assert config.enabled is True


def test_missing_key_file_disables(tmp_path: Path) -> None:
    config = ConnectionsConfig.from_env(
        {
            "ENABLEBANKING_APPLICATION_ID": "app-1",
            "ENABLEBANKING_KEY_PATH": str(tmp_path / "does-not-exist.pem"),
        }
    )
    assert config.enabled is False


def test_kill_switch_overrides_present_key(tmp_path: Path) -> None:
    key = tmp_path / "app.pem"
    key.write_text("x", encoding="utf-8")
    config = ConnectionsConfig.from_env(
        {
            "ENABLEBANKING_APPLICATION_ID": "app-1",
            "ENABLEBANKING_KEY_PATH": str(key),
            "PENGE_CONNECTIONS_ENABLED": "false",
        }
    )
    assert config.enabled is False


def test_redirect_url_override(tmp_path: Path) -> None:
    config = ConnectionsConfig.from_env({"PENGE_EB_REDIRECT_URL": "https://x/cb"})
    assert config.redirect_url == "https://x/cb"
