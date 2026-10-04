import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]
NAS = ROOT / "deploy" / "nas"


def _read(name: str) -> str:
    return (NAS / name).read_text()


def test_unresolved_chat_contract_is_non_deployable() -> None:
    validator = NAS / "validate-private-ask-chat.sh"

    seam = subprocess.run(  # noqa: S603  # Repository-owned validator under test.
        [validator, "--seam"],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    ready = subprocess.run(  # noqa: S603  # Repository-owned validator under test.
        [validator, "--ready"],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    contracted = subprocess.run(  # noqa: S603  # Repository-owned validator under test.
        [validator, "--ready"],
        cwd=ROOT,
        capture_output=True,
        check=False,
        env={**os.environ, "PENGE_CHAT_IMAGE_DIGEST": "a" * 64},
        text=True,
    )

    assert seam.returncode == 0, seam.stderr
    assert "fail-closed" in seam.stdout
    assert ready.returncode != 0
    assert "PENGE_CHAT_IMAGE_DIGEST must be an exact 64-character digest" in ready.stderr
    assert contracted.returncode != 0
    assert "deployment blocked by unresolved contracts" in contracted.stderr
    assert not (NAS / "penge-chat.container").exists()


def test_quadlet_template_is_rootless_immutable_and_loopback_only() -> None:
    quadlet = _read("penge-chat.container.in")
    installer = _read("install-private-ask-chat-quadlet.sh")

    assert "Image=ghcr.io/autoditac/penge/chat@sha256:@@CHAT_IMAGE_DIGEST@@" in quadlet
    assert "AutoUpdate=registry" not in quadlet
    assert ":main" not in quadlet
    assert ":latest" not in quadlet
    assert re.findall(r"^PublishPort=(.+)$", quadlet, re.MULTILINE) == [
        "127.0.0.1:8123:@@CHAT_HTTP_PORT@@"
    ]
    assert "SecurityLabelDisable" not in quadlet
    assert "ReadOnly=true" in quadlet
    assert "NoNewPrivileges=true" in quadlet
    assert "DropCapability=all" in quadlet
    assert "WantedBy=default.target" in quadlet
    assert "WantedBy=multi-user.target" not in quadlet
    assert "systemctl --user daemon-reload" in installer
    assert "refusing root execution" in installer
    assert "/etc/containers/systemd" not in installer
    assert "sudo" not in installer


def test_quadlet_has_only_versioned_secrets_and_no_transcript_volume() -> None:
    quadlet = _read("penge-chat.container.in")

    secrets = re.findall(r"^Secret=(.+)$", quadlet, re.MULTILINE)
    assert len(secrets) == 3
    assert all("_SECRET_VERSION@@" in secret for secret in secrets)
    assert all(",type=mount,target=@@" in secret for secret in secrets)
    assert "Volume=/var/lib/penge/chat" not in quadlet
    assert re.findall(r"^Volume=(.+)$", quadlet, re.MULTILINE) == [
        "@@MCP_READ_ONLY_SOURCE@@:@@MCP_READ_ONLY_TARGET@@:ro"
    ]


def test_live_nginx_fails_closed_on_only_bounded_ask_paths() -> None:
    nginx = _read("penge.eigmueller.de.conf")

    assert "location /ask {" not in nginx
    assert nginx.count("location = /ask {") == 1
    assert nginx.count("location ^~ /ask/ {") == 1
    assert "proxy_pass http://127.0.0.1:8123" not in nginx
    assert "location = /ask {\n        return 404;" in nginx
    assert "location ^~ /ask/ {\n        return 404;" in nginx


def test_candidate_nginx_overwrites_identity_without_weak_csp() -> None:
    nginx = _read("penge-chat.nginx.conf.in")

    assert "location = /ask {" in nginx
    assert "location ^~ /ask/ {" in nginx
    assert "X-Forwarded-User      $user" in nginx
    assert "X-Forwarded-Email     $email" in nginx
    assert "X-Forwarded-Client-Id $email" in nginx
    assert "script-src 'self'" in nginx
    assert "script-src 'self' 'unsafe-inline'" not in nginx
    assert "@@CHAT_UPSTREAM_WITH_EXPLICIT_BASE_PATH_SEMANTICS@@" in nginx
    assert "proxy_pass http://127.0.0.1:8123" not in nginx


def test_database_template_cannot_grant_non_oauth_data_access() -> None:
    sql = _read("penge-chat-db-role.sql.in")
    executable_sql = "\n".join(
        line for line in sql.splitlines() if not line.lstrip().startswith("--")
    ).lower()

    assert "@@oauth_link_tables_only@@" in executable_sql
    assert "grant select, insert, update, delete" in executable_sql
    assert "grant all" not in executable_sql
    assert "default privileges" not in executable_sql
    assert "analytics" not in executable_sql
    assert "finance" not in executable_sql
    assert "transcript" not in executable_sql


def test_architecture_contract_is_exact_but_activation_remains_unresolved() -> None:
    contract = _read("private-ask-chat.contract.env.in")

    assert "PENGE_CHAT_MODEL=hydrafusion" in contract
    assert "@@COPILOT_MODE_EMPTY_ENV_ASSIGNMENT@@" in contract
    assert "@@MODEL_FALLBACK_DISABLED_ENV_ASSIGNMENT@@" in contract
    assert "@@HYDRAFUSION_ENTITLEMENT_REQUIRED_ENV_ASSIGNMENT@@" in contract
    assert "@@SOURCE_COVERAGE_STARTUP_GATE_ENV_ASSIGNMENT@@" in contract
    assert "@@PROCESS_LOCAL_STDIO_MCP_ENV_ASSIGNMENT@@" in contract
    assert "@@DEFAULT_TOOLS_DISABLED_ENV_ASSIGNMENT@@" in contract
    assert "@@TRANSCRIPT_PERSISTENCE_DISABLED_ENV_ASSIGNMENT@@" in contract


def test_no_chat_mcp_or_runtime_listener_is_publicly_configured() -> None:
    public_config = "\n".join(
        (
            _read("penge.eigmueller.de.conf"),
            _read("penge-chat.container.in"),
            _read("penge-chat.nginx.conf.in"),
        )
    )

    published = re.findall(r"^PublishPort=(.+)$", public_config, re.MULTILINE)
    assert published == ["127.0.0.1:8123:@@CHAT_HTTP_PORT@@"]
    assert "0.0.0.0:" not in public_config
    assert "[::]:" not in public_config
    assert "mcp_pass" not in public_config.lower()
    assert "copilot-runtime" not in public_config.lower()
