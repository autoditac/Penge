import os
import re
import shutil
import stat
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

    if (ROOT / "apps" / "chat" / "package.json").exists():
        assert seam.returncode != 0
        assert contracted.returncode == 0, contracted.stderr
    else:
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
    assert len(re.findall(r"^Image=", quadlet, re.MULTILINE)) == 1
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
    assert "revoke all on database @@database_identifier@@ from public;" in executable_sql
    assert "revoke all on schema public from public;" in executable_sql
    assert "@@restore_required_non_chat_role_privileges_explicitly@@" in executable_sql


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


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _installer_fixture(tmp_path: Path, *, resolved: bool) -> tuple[Path, dict[str, str]]:
    repo = tmp_path / "repo"
    nas = repo / "deploy" / "nas"
    fake_bin = tmp_path / "bin"
    home = tmp_path / "home"
    contract_dir = home / ".config" / "penge"
    nas.mkdir(parents=True)
    fake_bin.mkdir()
    contract_dir.mkdir(parents=True)

    installer = nas / "install-private-ask-chat-quadlet.sh"
    shutil.copy2(NAS / installer.name, installer)
    template = _read("penge-chat.container.in")
    if resolved:
        replacements = {
            "@@CHAT_CONTAINER_GID@@": "1000",
            "@@CHAT_CONTAINER_UID@@": "1000",
            "@@CHAT_HEALTH_COMMAND@@": "/usr/bin/true",
            "@@CHAT_HEALTH_START_PERIOD@@": "10s",
            "@@CHAT_HTTP_PORT@@": "3000",
            "@@CHAT_ROOTLESS_NETWORK@@": "private-ask",
            "@@DATABASE_URL_SECRET_TARGET@@": "/run/secrets/database-url",
            "@@DATABASE_URL_SECRET_VERSION@@": "v1",
            "@@GITHUB_OAUTH_SECRET_TARGET@@": "/run/secrets/github-oauth",
            "@@GITHUB_OAUTH_SECRET_VERSION@@": "v1",
            "@@MCP_READ_ONLY_SOURCE@@": "/srv/penge/mcp",
            "@@MCP_READ_ONLY_TARGET@@": "/app/mcp",
            "@@TOKEN_KEYRING_SECRET_TARGET@@": "/run/secrets/token-keyring",
            "@@TOKEN_KEYRING_SECRET_VERSION@@": "v1",
        }
        for token, value in replacements.items():
            template = template.replace(token, value)
    (nas / "penge-chat.container.in").write_text(template)
    (contract_dir / "private-ask-chat.contract.env").write_text("PENGE_CHAT_MODEL=hydrafusion\n")
    (contract_dir / "private-ask-chat.contract-approved").touch()

    _write_executable(
        fake_bin / "id",
        '#!/bin/sh\nprintf "%s\\n" "${FAKE_ID_UID:-1000}"\n',
    )
    _write_executable(
        fake_bin / "podman",
        """#!/bin/sh
if [ "$1 $2" != "secret exists" ]; then
  exit 99
fi
if [ -n "${FAIL_SECRET:-}" ] && [ "$3" = "$FAIL_SECRET" ]; then
  exit 1
fi
exit 0
""",
    )
    _write_executable(
        fake_bin / "systemctl",
        '#!/bin/sh\nprintf "%s\\n" "$*" >"$SYSTEMCTL_LOG"\n',
    )
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "SYSTEMCTL_LOG": str(tmp_path / "systemctl.log"),
    }
    return installer, env


def test_installer_rejects_invalid_input_root_and_missing_approval(tmp_path: Path) -> None:
    installer, env = _installer_fixture(tmp_path, resolved=False)
    digest = "a" * 64

    invalid = subprocess.run(  # noqa: S603  # Temporary installer copy under test.
        [installer, "not-a-digest"],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )
    root = subprocess.run(  # noqa: S603  # Temporary installer copy under test.
        [installer, digest],
        capture_output=True,
        check=False,
        env={**env, "FAKE_ID_UID": "0"},
        text=True,
    )
    approval = Path(env["HOME"]) / ".config" / "penge" / ("private-ask-chat.contract-approved")
    approval.unlink()
    missing = subprocess.run(  # noqa: S603  # Temporary installer copy under test.
        [installer, digest],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )

    assert invalid.returncode == 2
    assert root.returncode != 0
    assert "refusing root execution" in root.stderr
    assert missing.returncode != 0
    assert "approval marker" in missing.stderr


def test_installer_rejects_unresolved_environment_and_quadlet(tmp_path: Path) -> None:
    installer, env = _installer_fixture(tmp_path, resolved=False)
    digest = "a" * 64
    contract = Path(env["HOME"]) / ".config" / "penge" / ("private-ask-chat.contract.env")
    contract.write_text("@@MODEL_FALLBACK_DISABLED_ENV_ASSIGNMENT@@\n")

    environment = subprocess.run(  # noqa: S603  # Temporary installer copy under test.
        [installer, digest],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )
    contract.write_text("PENGE_CHAT_MODEL=hydrafusion\n")
    quadlet = subprocess.run(  # noqa: S603  # Temporary installer copy under test.
        [installer, digest],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )

    assert environment.returncode != 0
    assert "unresolved private Ask environment tokens" in environment.stderr
    assert quadlet.returncode != 0
    assert "unresolved private Ask contract tokens" in quadlet.stderr


def test_installer_checks_secrets_and_writes_private_user_unit(tmp_path: Path) -> None:
    installer, env = _installer_fixture(tmp_path, resolved=True)
    digest = "a" * 64
    missing_mount = "penge-chat-token-keyring-v1"

    missing = subprocess.run(  # noqa: S603  # Temporary installer copy under test.
        [installer, digest],
        capture_output=True,
        check=False,
        env={**env, "FAIL_SECRET": missing_mount},
        text=True,
    )
    installed = subprocess.run(  # noqa: S603  # Temporary installer copy under test.
        [installer, digest],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )

    unit_dir = Path(env["HOME"]) / ".config" / "containers" / "systemd"
    unit = unit_dir / "penge-chat.container"
    assert missing.returncode != 0
    assert f"missing rootless Podman secret {missing_mount}" in missing.stderr
    assert installed.returncode == 0, installed.stderr
    assert unit.stat().st_mode & 0o777 == 0o600
    assert unit_dir.stat().st_mode & 0o777 == 0o700
    assert unit.read_text().count("Image=") == 1
    assert f"@sha256:{digest}" in unit.read_text()
    assert (tmp_path / "systemctl.log").read_text().strip() == "--user daemon-reload"
