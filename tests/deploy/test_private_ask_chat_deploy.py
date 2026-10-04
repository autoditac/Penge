import hashlib
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
    assert (
        "EnvironmentFile=%h/.config/penge/approved/"
        "private-ask-chat.contract-@@CONTRACT_ENV_SHA256@@.env"
    ) in quadlet
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
    assert "current_database() <> '@@chat_oauth_database_name@@'" in executable_sql
    assert (
        "revoke all on database @@chat_oauth_database_identifier@@ from public;" in executable_sql
    )
    assert "revoke all on schema public from public;" in executable_sql
    assert "@@database_identifier@@" not in executable_sql
    assert "penge" not in executable_sql
    assert "alter role" not in executable_sql
    assert "grant create" not in executable_sql


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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_approval_manifest(repo: Path, home: Path, digest: str) -> Path:
    nas = repo / "deploy" / "nas"
    contract_dir = home / ".config" / "penge"
    contract = contract_dir / "private-ask-chat.contract.env"
    template = nas / "penge-chat.container.in"
    contract_hash = _sha256(contract)
    rendered = (
        template.read_text()
        .replace("@@CHAT_IMAGE_DIGEST@@", digest)
        .replace("@@CONTRACT_ENV_SHA256@@", contract_hash)
    )
    approval = contract_dir / "private-ask-chat.approval.manifest"
    approval.write_text(
        "\n".join(
            (
                "version=1",
                "decision=approved",
                "reviewed_by=synthetic-reviewer",
                (
                    "review_reference=https://github.com/autoditac/Penge/"
                    "pull/347#pullrequestreview-1"
                ),
                f"image_digest={digest}",
                f"contract_env_sha256={contract_hash}",
                f"quadlet_template_sha256={_sha256(template)}",
                (f"rendered_quadlet_sha256={hashlib.sha256(rendered.encode()).hexdigest()}"),
                f"nginx_template_sha256={_sha256(nas / 'penge-chat.nginx.conf.in')}",
                f"database_template_sha256={_sha256(nas / 'penge-chat-db-role.sql.in')}",
                (
                    "contract_env_template_sha256="
                    f"{_sha256(nas / 'private-ask-chat.contract.env.in')}"
                ),
                "",
            )
        )
    )
    approval.chmod(0o600)
    return approval


def _installer_fixture(tmp_path: Path, *, resolved: bool) -> tuple[Path, dict[str, str]]:
    repo = tmp_path / "repo"
    nas = repo / "deploy" / "nas"
    fake_bin = tmp_path / "bin"
    home = tmp_path / "home"
    contract_dir = home / ".config" / "penge"
    nas.mkdir(parents=True)
    fake_bin.mkdir()
    contract_dir.mkdir(parents=True)

    for name in (
        "install-private-ask-chat-quadlet.sh",
        "penge-chat-db-role.sql.in",
        "penge-chat.nginx.conf.in",
        "private-ask-chat.contract.env.in",
    ):
        shutil.copy2(NAS / name, nas / name)
    installer = nas / "install-private-ask-chat-quadlet.sh"
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
    contract = contract_dir / "private-ask-chat.contract.env"
    contract.write_text("PENGE_CHAT_MODEL=hydrafusion\n")
    contract.chmod(0o600)
    _write_approval_manifest(repo, home, "a" * 64)

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
    _write_executable(
        fake_bin / "stat",
        """#!/bin/sh
if [ -n "${FAKE_STAT_OWNER:-}" ] && [ "$1 $2" = "-c %u %a" ]; then
  mode=$(/usr/bin/stat -c %a "$3")
  printf "%s %s\\n" "$FAKE_STAT_OWNER" "$mode"
  exit 0
fi
exec /usr/bin/stat "$@"
""",
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
    approval = Path(env["HOME"]) / ".config" / "penge" / "private-ask-chat.approval.manifest"
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
    assert "approval manifest" in missing.stderr


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


def test_installer_rejects_unsafe_contract_and_manifest_metadata(tmp_path: Path) -> None:
    installer, env = _installer_fixture(tmp_path, resolved=True)
    digest = "a" * 64
    contract_dir = Path(env["HOME"]) / ".config" / "penge"
    contract = contract_dir / "private-ask-chat.contract.env"
    approval = contract_dir / "private-ask-chat.approval.manifest"

    contract.chmod(0o640)
    unsafe_contract = subprocess.run(  # noqa: S603  # Temporary installer copy under test.
        [installer, digest],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )
    contract.chmod(0o600)
    approval.chmod(0o644)
    unsafe_manifest = subprocess.run(  # noqa: S603  # Temporary installer copy under test.
        [installer, digest],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )
    approval.chmod(0o600)
    wrong_owner = subprocess.run(  # noqa: S603  # Temporary installer copy under test.
        [installer, digest],
        capture_output=True,
        check=False,
        env={**env, "FAKE_STAT_OWNER": "9999"},
        text=True,
    )

    assert "contract environment must use mode 0400 or 0600" in unsafe_contract.stderr
    assert "approval manifest must use mode 0400 or 0600" in unsafe_manifest.stderr
    assert "contract environment must be owned by uid 1000" in wrong_owner.stderr


def test_installer_invalidates_stale_artifact_and_digest_approval(tmp_path: Path) -> None:
    installer, env = _installer_fixture(tmp_path, resolved=True)
    digest = "a" * 64
    repo = installer.parents[2]
    contract = Path(env["HOME"]) / ".config" / "penge" / ("private-ask-chat.contract.env")

    wrong_digest = subprocess.run(  # noqa: S603  # Temporary installer copy under test.
        [installer, "b" * 64],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )
    contract.write_text("PENGE_CHAT_MODEL=hydrafusion\nPENGE_EXTRA=changed\n")
    changed_contract = subprocess.run(  # noqa: S603  # Temporary installer copy under test.
        [installer, digest],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )
    contract.write_text("PENGE_CHAT_MODEL=hydrafusion\n")
    template = repo / "deploy" / "nas" / "penge-chat.container.in"
    template.write_text(f"{template.read_text()}# changed after approval\n")
    changed_template = subprocess.run(  # noqa: S603  # Temporary installer copy under test.
        [installer, digest],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )

    assert "image digest is not approved" in wrong_digest.stderr
    assert "approval hash mismatch for contract_env_sha256" in changed_contract.stderr
    assert "approval hash mismatch for quadlet_template_sha256" in changed_template.stderr


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
    approved_dir = Path(env["HOME"]) / ".config" / "penge" / "approved"
    assert missing.returncode != 0
    assert f"missing rootless Podman secret {missing_mount}" in missing.stderr
    assert installed.returncode == 0, installed.stderr
    assert unit.stat().st_mode & 0o777 == 0o600
    assert unit_dir.stat().st_mode & 0o777 == 0o700
    approved_contracts = list(approved_dir.glob("private-ask-chat.contract-*.env"))
    assert len(approved_contracts) == 1
    assert approved_contracts[0].stat().st_mode & 0o777 == 0o600
    assert _sha256(approved_contracts[0]) in unit.read_text()
    assert unit.read_text().count("Image=") == 1
    assert f"@sha256:{digest}" in unit.read_text()
    assert (tmp_path / "systemctl.log").read_text().strip() == "--user daemon-reload"
