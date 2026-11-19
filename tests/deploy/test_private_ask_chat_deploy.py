import hashlib
import http.client
import os
import re
import shutil
import socket
import stat
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
NAS = ROOT / "deploy" / "nas"
SSH_KEYGEN = Path("/usr/bin/ssh-keygen")
CHAT_APP_PRESENT = (ROOT / "apps" / "chat" / "package.json").exists()
CONTRACT_TEMPLATES = (
    "penge-chat.container.in",
    "penge-chat.nginx.conf.in",
    "penge-chat-db-role.sql.in",
    "private-ask-chat.contract.env.in",
)
DEPLOYMENT_TIME_TOKENS = {"@@CHAT_IMAGE_DIGEST@@", "@@CONTRACT_ENV_SHA256@@"}
CONTRACTS_RESOLVED = not any(
    set(re.findall(r"@@[A-Z0-9_]+@@", (NAS / name).read_text())) - DEPLOYMENT_TIME_TOKENS
    for name in CONTRACT_TEMPLATES
)
CONTRACT_REPLACEMENTS = {
    "@@COPILOT_MODE_EMPTY_ENV_ASSIGNMENT@@": "PENGE_COPILOT_MODE=empty",
    "@@DEFAULT_TOOLS_DISABLED_ENV_ASSIGNMENT@@": "PENGE_DEFAULT_TOOLS=false",
    "@@HYDRAFUSION_ENTITLEMENT_REQUIRED_ENV_ASSIGNMENT@@": ("PENGE_REQUIRE_HYDRAFUSION=true"),
    "@@MODEL_FALLBACK_DISABLED_ENV_ASSIGNMENT@@": "PENGE_MODEL_FALLBACK=false",
    "@@PRIVACY_SAFE_METRICS_ENV_ASSIGNMENT@@": "PENGE_METRICS_MODE=private",
    "@@PRIVACY_SAFE_STRUCTURED_LOGGING_ENV_ASSIGNMENT@@": "PENGE_LOG_MODE=redacted",
    "@@PROCESS_LOCAL_STDIO_MCP_ENV_ASSIGNMENT@@": "PENGE_MCP_TRANSPORT=stdio",
    "@@SOURCE_COVERAGE_STARTUP_GATE_ENV_ASSIGNMENT@@": ("PENGE_REQUIRE_SOURCE_COVERAGE=true"),
    "@@TRANSCRIPT_PERSISTENCE_DISABLED_ENV_ASSIGNMENT@@": ("PENGE_TRANSCRIPT_PERSISTENCE=false"),
    "@@DATABASE_URL_SECRET_TARGET@@": "/run/secrets/chat-database-url",
    "@@FINANCE_MCP_DATABASE_URL_SECRET_TARGET@@": ("/run/secrets/finance-mcp-database-url"),
    "@@CHAT_PUBLIC_API_BASE_WITH_TRAILING_SLASH@@": ("https://chat.example.test/ask/api/"),
    "@@CHAT_PUBLIC_APP_ORIGIN@@": "https://chat.example.test",
    "@@GITHUB_CLIENT_ID@@": "synthetic-client-id",
    "@@GITHUB_CLIENT_SECRET_TARGET@@": "/run/secrets/github-client-secret",
    "@@TOKEN_KEYRING_SECRET_TARGET@@": "/run/secrets/token-keyring",
    "@@IDENTITY_PEPPER_SECRET_TARGET@@": "/run/secrets/identity-pepper",
    "@@PROXY_SECRET_TARGET@@": "/run/secrets/proxy-secret",
    "@@TRUSTED_PROXY_ISSUER@@": "penge-oauth2-proxy",
}


def _read(name: str) -> str:
    return (NAS / name).read_text()


def _resolved_contract_environment() -> str:
    contract = _read("private-ask-chat.contract.env.in")
    for token, value in CONTRACT_REPLACEMENTS.items():
        contract = contract.replace(token, value)
    return contract


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

    if CONTRACTS_RESOLVED:
        assert seam.returncode != 0
        if CHAT_APP_PRESENT:
            assert contracted.returncode != 0
        else:
            assert contracted.returncode != 0
            assert "missing backend packaging contract" in contracted.stderr
    else:
        assert seam.returncode == 0, seam.stderr
        assert "fail-closed" in seam.stdout
        assert ready.returncode != 0
        assert "PENGE_CHAT_IMAGE_DIGEST must be an exact 64-character digest" in ready.stderr
        assert contracted.returncode != 0
        assert "deployment blocked by unresolved contracts" in contracted.stderr
        assert not (NAS / "penge-chat.container").exists()


def test_quadlet_template_is_rootless_immutable_and_has_no_published_port() -> None:
    quadlet = _read("penge-chat.container.in")
    installer = _read("install-private-ask-chat-quadlet.sh")

    assert "Image=ghcr.io/autoditac/penge/chat@sha256:@@CHAT_IMAGE_DIGEST@@" in quadlet
    assert "AutoUpdate=registry" not in quadlet
    assert ":main" not in quadlet
    assert ":latest" not in quadlet
    assert len(re.findall(r"^Image=", quadlet, re.MULTILINE)) == 1
    published = re.findall(r"^PublishPort=(.+)$", quadlet, re.MULTILINE)
    assert not published
    assert "SecurityLabelDisable" not in quadlet
    assert "ReadOnly=true" in quadlet
    assert "NoNewPrivileges=true" in quadlet
    assert "DropCapability=all" in quadlet
    assert (
        "EnvironmentFile=%h/.config/penge/approved/"
        "private-ask-chat.contract-@@CONTRACT_ENV_SHA256@@.env"
    ) in quadlet
    assert "[Install]" not in quadlet
    assert "systemctl --user daemon-reload" in installer
    assert "refusing root execution" in installer
    assert "/etc/containers/systemd" not in installer
    assert "sudo" not in installer


def test_quadlet_has_only_versioned_secrets_and_no_transcript_volume() -> None:
    quadlet = _read("penge-chat.container.in")

    secrets = re.findall(r"^Secret=(.+)$", quadlet, re.MULTILINE)
    assert len(secrets) == 6
    if CONTRACTS_RESOLVED:
        assert all("@@" not in secret for secret in secrets)
    else:
        assert all("_SECRET_VERSION@@" in secret for secret in secrets)
        assert all(",type=mount,target=@@" in secret for secret in secrets)
    assert "Volume=/var/lib/penge/chat" not in quadlet
    volumes = re.findall(r"^Volume=(.+)$", quadlet, re.MULTILINE)
    assert len(volumes) == 2
    assert any(volume.endswith(":ro") for volume in volumes)
    if not CONTRACTS_RESOLVED:
        assert "@@MCP_READ_ONLY_SOURCE@@:@@MCP_READ_ONLY_TARGET@@:ro" in volumes
        assert (
            "@@CHAT_SOCKET_HOST_DIR@@:/run/penge-chat/transport:@@CHAT_SOCKET_VOLUME_OPTIONS@@"
            in volumes
        )


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
    location = re.search(r"location \^~ (?P<prefix>/[^ ]+) \{", nginx)
    proxy_pass = re.search(r"proxy_pass (?P<upstream>http://unix:[^;]+/chat\.sock:/);", nginx)

    assert location is not None
    assert proxy_pass is not None
    api_prefix = location.group("prefix")

    def upstream_path(public_path: str) -> str | None:
        if not public_path.startswith(api_prefix):
            return None
        return f"/{public_path.removeprefix(api_prefix)}"

    assert "location = /ask {" not in nginx
    assert "location ^~ /ask/ {" not in nginx
    assert "location ^~ /ask/api/ {" in nginx
    assert "location ^~ /ask/api/ {\n    access_log off;" in nginx
    assert "location = /_penge_chat_auth {\n    internal;\n    access_log off;" in nginx
    assert nginx.count("error_log /dev/null emerg;") == 2
    assert "auth_request /_penge_chat_auth;" in nginx
    assert "error_page 401" not in nginx
    assert "proxy_pass http://unix:@@CHAT_SOCKET_HOST_DIR@@/chat.sock:/;" in nginx
    assert 'proxy_set_header X-Forwarded-User "";' in nginx
    assert 'proxy_set_header X-Forwarded-Email "";' in nginx
    assert 'proxy_set_header X-Forwarded-Client-Id "";' in nginx
    assert 'proxy_set_header X-Login "";' in nginx
    assert 'proxy_set_header X-User "";' in nginx
    assert nginx.count("proxy_set_header x-penge-auth-issuer ") == 1
    assert nginx.count("proxy_set_header x-penge-auth-subject ") == 1
    assert nginx.count("proxy_set_header x-penge-proxy-secret ") == 1
    assert upstream_path("/ask/api/v1/chat") == "/v1/chat"
    assert upstream_path("/ask/api/oauth/github/callback") == "/oauth/github/callback"
    assert upstream_path("/ask/oauth/github/callback") is None
    assert upstream_path("/ask/") is None
    assert "script-src 'self'" in nginx
    assert "script-src 'self' 'unsafe-inline'" not in nginx
    if CONTRACTS_RESOLVED:
        assert "@@" not in nginx
    else:
        assert "@@TRUSTED_PROXY_ISSUER_NGINX_VALUE@@" in nginx
        assert "@@IMMUTABLE_AUTH_SUBJECT_NGINX_VALUE@@" in nginx
        assert "@@MOUNTED_PROXY_SECRET_NGINX_VALUE@@" in nginx


def _nginx_test_config(tmp_path: Path, auth_port: int, port: int) -> Path:
    template = _read("penge-chat.nginx.conf.in")
    replacements = {
        "127.0.0.1:4180": f"127.0.0.1:{auth_port}",
        "@@CHAT_SOCKET_HOST_DIR@@": str(tmp_path),
        "@@IMMUTABLE_AUTH_SUBJECT_NGINX_VALUE@@": "synthetic-subject",
        "@@MOUNTED_PROXY_SECRET_NGINX_VALUE@@": "synthetic-proxy-secret",
        "@@TRUSTED_PROXY_ISSUER_NGINX_VALUE@@": "synthetic-issuer",
        "@@STREAMING_READ_TIMEOUT@@": "30s",
        "@@STREAMING_REQUEST_BUFFERING@@": "off",
        "@@STREAMING_RESPONSE_BUFFERING@@": "off",
        "@@STREAMING_SEND_TIMEOUT@@": "30s",
    }
    for token, value in replacements.items():
        template = template.replace(token, value)
    (tmp_path / "logs").mkdir()
    (tmp_path / "probe").write_text("ok")
    config = tmp_path / "nginx.conf"
    config.write_text(
        f"daemon off;\nmaster_process off;\npid {tmp_path}/nginx.pid;\n"
        f"error_log {tmp_path}/error.log info;\nevents {{}}\nhttp {{\n"
        f"access_log {tmp_path}/access.log;\nserver {{\nlisten 127.0.0.1:{port};\n"
        f"location = /probe {{ root {tmp_path}; }}\n{template}\n}}\n}}\n"
    )
    return config


@pytest.mark.skipif(shutil.which("nginx") is None, reason="nginx binary is unavailable")
@pytest.mark.parametrize(("auth_status", "expected_status"), [(204, 502), (401, 401)])
def test_nginx_callback_failure_never_logs_oauth_parameters(
    tmp_path: Path, auth_status: int, expected_status: int
) -> None:
    auth_paths: list[str] = []

    class AuthHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            auth_paths.append(self.path)
            self.send_response(auth_status)
            self.end_headers()

        def log_message(self, _format: str, *_args: object) -> None:
            pass

    nginx = shutil.which("nginx")
    assert nginx is not None
    with (
        ThreadingHTTPServer(("127.0.0.1", 0), AuthHandler) as auth,
        socket.socket() as listener,
    ):
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        listener.close()
        auth_thread = threading.Thread(target=auth.serve_forever, daemon=True)
        auth_thread.start()
        access_log = tmp_path / "access.log"
        error_log = tmp_path / "error.log"
        config = _nginx_test_config(tmp_path, auth.server_port, port)
        process = subprocess.Popen(  # noqa: S603  # Located nginx binary with synthetic config.
            [nginx, "-p", str(tmp_path), "-c", str(config)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
            deadline = time.monotonic() + 5
            while True:
                try:
                    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
                    connection.request("GET", "/probe")
                    assert connection.getresponse().status == 200
                    connection.close()
                    break
                except OSError:
                    if process.poll() is not None:
                        _, stderr = process.communicate(timeout=5)
                        pytest.fail(f"nginx failed to start: {stderr.decode()}")
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.05)
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            connection.request(
                "GET",
                "/ask/api/oauth/github/callback?code=synthetic_code&state=synthetic_state",
            )
            response = connection.getresponse()
            assert response.status == expected_status
            response.read()
            connection.close()
        finally:
            process.terminate()
            process.communicate(timeout=5)
            auth.shutdown()
            auth_thread.join(timeout=5)

        assert "/probe" in access_log.read_text()
        logs = access_log.read_text() + error_log.read_text()
        assert "synthetic_code" not in logs
        assert "synthetic_state" not in logs
        assert auth_paths == ["/oauth2/auth"]


def test_database_template_cannot_grant_non_oauth_data_access() -> None:
    sql = _read("penge-chat-db-role.sql.in")
    executable_sql = "\n".join(
        line for line in sql.splitlines() if not line.lstrip().startswith("--")
    ).lower()

    assert "grant select, insert, update, delete" in executable_sql
    assert "chat_oauth_link" in executable_sql
    assert "chat_oauth_state" in executable_sql
    assert "grant insert" in executable_sql
    assert "chat_audit_event" in executable_sql
    assert "grant usage, select" in executable_sql
    assert "chat_audit_event_id_seq" in executable_sql
    assert "grant all" not in executable_sql
    assert "default privileges" not in executable_sql
    assert "analytics" not in executable_sql
    assert "finance" not in executable_sql
    assert "transcript" not in executable_sql
    if CONTRACTS_RESOLVED:
        assert "@@" not in executable_sql
    else:
        assert "current_database() <> '@@chat_oauth_database_name@@'" in executable_sql
        assert (
            'revoke all on database "@@chat_oauth_database_name@@" from public;' in executable_sql
        )
    assert "revoke all on schema public from public;" in executable_sql
    assert "@@database_identifier@@" not in executable_sql
    assert 'database "penge"' not in executable_sql
    assert "current_database() <> 'penge'" not in executable_sql
    assert "alter role" not in executable_sql
    assert "grant create" not in executable_sql


def test_architecture_contract_is_exact_but_activation_remains_unresolved() -> None:
    contract = _read("private-ask-chat.contract.env.in")

    assert "PENGE_CHAT_MODEL=hydrafusion" in contract
    for name in (
        "PENGE_CHAT_GITHUB_CLIENT_ID",
        "PENGE_CHAT_GITHUB_CLIENT_SECRET_FILE",
        "PENGE_CHAT_TOKEN_KEYRING_FILE",
        "PENGE_CHAT_IDENTITY_PEPPER_FILE",
        "PENGE_CHAT_PROXY_SHARED_SECRET_FILE",
        "PENGE_CHAT_TRUSTED_PROXY_ISSUER",
        "PENGE_CHAT_PUBLIC_API_BASE",
        "PENGE_CHAT_PUBLIC_APP_ORIGIN",
        "PENGE_CHAT_DATABASE_URL_FILE",
        "PENGE_DB_URL_FILE",
    ):
        assert contract.count(f"{name}=") == 1
    assert "PENGE_CHAT_GITHUB_OAUTH_FILE" not in contract
    assert "PENGE_CHAT_MIGRATION_DATABASE_URL_FILE" not in contract
    if CONTRACTS_RESOLVED:
        assert "@@" not in contract
    else:
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
    assert not published
    assert "0.0.0.0:" not in public_config
    assert "[::]:" not in public_config
    assert "mcp_pass" not in public_config.lower()
    assert "copilot-runtime" not in public_config.lower()


def test_ci_keeps_seam_gate_until_an_attested_digest_is_wired() -> None:
    workflow = (ROOT / ".github" / "workflows" / "private-ask-chat-deployment.yml").read_text()

    assert "validate-private-ask-chat.sh --seam" in workflow
    assert "validate-private-ask-chat.sh --ready" not in workflow


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _ready_validator_fixture(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    repo = tmp_path / "ready-repo"
    nas = repo / "deploy" / "nas"
    chat = repo / "apps" / "chat"
    workflows = repo / ".github" / "workflows"
    nas.mkdir(parents=True)
    chat.mkdir(parents=True)
    workflows.mkdir(parents=True)

    for name in (
        "validate-private-ask-chat.sh",
        "install-private-ask-chat-quadlet.sh",
        "penge.eigmueller.de.conf",
    ):
        shutil.copy2(NAS / name, nas / name)

    quadlet = _read("penge-chat.container.in")
    quadlet_replacements = {
        "@@CHAT_CONTAINER_GID@@": "1000",
        "@@CHAT_CONTAINER_UID@@": "1000",
        "@@CHAT_HEALTH_COMMAND@@": "/usr/bin/true",
        "@@CHAT_HEALTH_START_PERIOD@@": "10s",
        "@@CHAT_SOCKET_HOST_DIR@@": "/srv/penge/chat-socket",
        "@@CHAT_SOCKET_VOLUME_OPTIONS@@": "rw",
        "@@CHAT_ROOTLESS_NETWORK@@": "private-ask",
        "@@DATABASE_URL_SECRET_TARGET@@": "/run/secrets/chat-database-url",
        "@@DATABASE_URL_SECRET_VERSION@@": "v1",
        "@@FINANCE_MCP_DATABASE_URL_SECRET_TARGET@@": ("/run/secrets/finance-mcp-database-url"),
        "@@FINANCE_MCP_DATABASE_URL_SECRET_VERSION@@": "v1",
        "@@GITHUB_CLIENT_SECRET_TARGET@@": "/run/secrets/github-client-secret",
        "@@GITHUB_CLIENT_SECRET_VERSION@@": "v1",
        "@@IDENTITY_PEPPER_SECRET_TARGET@@": "/run/secrets/identity-pepper",
        "@@IDENTITY_PEPPER_SECRET_VERSION@@": "v1",
        "@@MCP_READ_ONLY_SOURCE@@": "/srv/penge/mcp",
        "@@MCP_READ_ONLY_TARGET@@": "/app/mcp",
        "@@PROXY_SECRET_TARGET@@": "/run/secrets/proxy-secret",
        "@@PROXY_SECRET_VERSION@@": "v1",
        "@@TOKEN_KEYRING_SECRET_TARGET@@": "/run/secrets/token-keyring",
        "@@TOKEN_KEYRING_SECRET_VERSION@@": "v1",
    }
    for token, value in quadlet_replacements.items():
        quadlet = quadlet.replace(token, value)
    (nas / "penge-chat.container.in").write_text(quadlet)

    nginx = _read("penge-chat.nginx.conf.in")
    nginx_replacements = {
        "@@CHAT_SOCKET_HOST_DIR@@": "/srv/penge/chat-socket",
        "@@IMMUTABLE_AUTH_SUBJECT_NGINX_VALUE@@": "$penge_auth_subject",
        "@@MOUNTED_PROXY_SECRET_NGINX_VALUE@@": "$penge_proxy_secret",
        "@@TRUSTED_PROXY_ISSUER_NGINX_VALUE@@": "penge-oauth2-proxy",
        "@@STREAMING_READ_TIMEOUT@@": "300s",
        "@@STREAMING_REQUEST_BUFFERING@@": "off",
        "@@STREAMING_RESPONSE_BUFFERING@@": "off",
        "@@STREAMING_SEND_TIMEOUT@@": "300s",
    }
    for token, value in nginx_replacements.items():
        nginx = nginx.replace(token, value)
    (nas / "penge-chat.nginx.conf.in").write_text(nginx)

    database = _read("penge-chat-db-role.sql.in")
    database_replacements = {
        "@@CHAT_DATABASE_ROLE@@": "penge_chat_oauth",
        "@@CHAT_OAUTH_DATABASE_NAME@@": "penge_chat_oauth",
        "@@CREATE_DEDICATED_CHAT_ROLE_WITH_SECRET_MANAGED_LOGIN@@": (
            "CREATE ROLE penge_chat_oauth LOGIN NOSUPERUSER NOCREATEDB "
            "NOCREATEROLE NOINHERIT NOBYPASSRLS;"
        ),
        "@@OAUTH_LINK_SCHEMA@@": "public",
    }
    for token, value in database_replacements.items():
        database = database.replace(token, value)
    (nas / "penge-chat-db-role.sql.in").write_text(database)

    (nas / "private-ask-chat.contract.env.in").write_text(_resolved_contract_environment())

    (chat / "package.json").write_text('{"dependencies":{"@github/copilot-sdk":"1.0.16"}}\n')
    (repo / "pnpm-lock.yaml").write_text(
        """lockfileVersion: '9.0'
importers:
  apps/chat:
    dependencies:
      '@github/copilot-sdk':
        specifier: 1.0.16
        version: 1.0.16
packages:
  '@github/copilot-sdk@1.0.16': {}
"""
    )
    (chat / "Containerfile").write_text(
        "\n".join(
            (
                f"FROM node@sha256:{'a' * 64} AS build",
                "COPY pnpm-lock.yaml ./",
                "RUN pnpm install --frozen-lockfile",
                "FROM build AS runtime",
                "",
            )
        )
    )
    for name in ("ci.yml", "release.yml"):
        (workflows / name).write_text("matrix:\n  app: [web, api, chat]\n")

    return nas / "validate-private-ask-chat.sh", {
        **os.environ,
        "PENGE_CHAT_IMAGE_DIGEST": "b" * 64,
    }


def test_ready_validator_blocks_unreviewed_transport_even_when_other_contracts_resolve(
    tmp_path: Path,
) -> None:
    validator, env = _ready_validator_fixture(tmp_path)

    ready = subprocess.run(  # noqa: S603  # Temporary validator copy under test.
        [validator, "--ready"],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )
    containerfile = validator.parents[2] / "apps" / "chat" / "Containerfile"
    containerfile.write_text(f"{containerfile.read_text()}FROM alpine:3.22 AS unsafe\n")
    mutable = subprocess.run(  # noqa: S603  # Temporary validator copy under test.
        [validator, "--ready"],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )

    assert ready.returncode != 0
    assert "socket transport requires reviewed container connectivity" in ready.stderr
    assert mutable.returncode != 0
    assert "external base image is not digest-pinned: alpine:3.22" in mutable.stderr


def test_ready_validator_rejects_malformed_containerfile_from(
    tmp_path: Path,
) -> None:
    validator, env = _ready_validator_fixture(tmp_path)
    containerfile = validator.parents[2] / "apps" / "chat" / "Containerfile"
    containerfile.write_text(f"{containerfile.read_text()}FROM --platform=linux/amd64\n")

    malformed = subprocess.run(  # noqa: S603  # Temporary validator copy under test.
        [validator, "--ready"],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )

    assert malformed.returncode != 0
    assert "chat Containerfile has a malformed FROM directive" in malformed.stderr


def test_ready_validator_rejects_security_marker_bound_to_wrong_assignment(
    tmp_path: Path,
) -> None:
    validator, env = _ready_validator_fixture(tmp_path)
    contract = validator.parent / "private-ask-chat.contract.env.in"
    contract.write_text(
        contract.read_text().replace(
            "PENGE_MODEL_FALLBACK=false",
            "UNUSED=false",
        )
    )

    unsafe = subprocess.run(  # noqa: S603  # Temporary validator copy under test.
        [validator, "--ready"],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )

    assert unsafe.returncode != 0
    assert "unsafe model-fallback assignment" in unsafe.stderr


def test_ready_validator_rejects_mismatched_database_privilege_target(
    tmp_path: Path,
) -> None:
    validator, env = _ready_validator_fixture(tmp_path)
    database = validator.parent / "penge-chat-db-role.sql.in"
    database.write_text(
        database.read_text().replace(
            'REVOKE ALL ON DATABASE "penge_chat_oauth" FROM penge_chat_oauth;',
            'REVOKE ALL ON DATABASE "other_chat_oauth" FROM penge_chat_oauth;',
        )
    )

    mismatched = subprocess.run(  # noqa: S603  # Temporary validator copy under test.
        [validator, "--ready"],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )

    assert mismatched.returncode != 0
    assert "database guard and privilege target differ" in mismatched.stderr


def test_ready_validator_rejects_non_public_oauth_schema(tmp_path: Path) -> None:
    validator, env = _ready_validator_fixture(tmp_path)
    database = validator.parent / "penge-chat-db-role.sql.in"
    database.write_text(
        database.read_text()
        .replace("GRANT USAGE ON SCHEMA public TO", "GRANT USAGE ON SCHEMA oauth TO")
        .replace("public.chat_", "oauth.chat_")
    )
    rejected = subprocess.run(  # noqa: S603  # Temporary validator copy under test.
        [validator, "--ready"], capture_output=True, check=False, env=env, text=True
    )
    assert rejected.returncode != 0
    assert "OAuth schema must be public" in rejected.stderr


def test_ready_validator_rejects_additional_database_grant(tmp_path: Path) -> None:
    validator, env = _ready_validator_fixture(tmp_path)
    database = validator.parent / "penge-chat-db-role.sql.in"
    database.write_text(
        database.read_text().replace(
            "COMMIT;",
            "GRANT SELECT ON TABLE public.other_table TO penge_chat_oauth;\n\nCOMMIT;",
        )
    )

    excessive = subprocess.run(  # noqa: S603  # Temporary validator copy under test.
        [validator, "--ready"],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )

    assert excessive.returncode != 0
    assert "unexpected GRANT or REVOKE shape" in excessive.stderr


def test_ready_validator_rejects_widened_existing_database_grants(tmp_path: Path) -> None:
    validator, env = _ready_validator_fixture(tmp_path)
    database = validator.parent / "penge-chat-db-role.sql.in"
    safe_database = database.read_text()
    mutations = (
        (
            "GRANT INSERT\n    ON TABLE public.chat_audit_event",
            "GRANT SELECT, INSERT, UPDATE, DELETE\n    ON TABLE public.chat_audit_event",
            "exact approved database privilege shape",
        ),
        (
            "public.chat_oauth_state\n",
            "public.chat_oauth_state,\n        public.other_table\n",
            "exact approved database privilege shape",
        ),
        (
            "COMMIT;",
            "ALTER TABLE public.chat_audit_event OWNER TO penge_chat_oauth;\nCOMMIT;",
            "chat database privilege targets are incomplete",
        ),
    )

    for original, replacement, expected_error in mutations:
        assert original in safe_database
        database.write_text(safe_database.replace(original, replacement))
        rejected = subprocess.run(  # noqa: S603  # Temporary validator copy under test.
            [validator, "--ready"], capture_output=True, check=False, env=env, text=True
        )
        assert rejected.returncode != 0
        assert expected_error in rejected.stderr


def test_ready_validator_rejects_nginx_request_logging(tmp_path: Path) -> None:
    validator, env = _ready_validator_fixture(tmp_path)
    nginx = validator.parent / "penge-chat.nginx.conf.in"
    safe_nginx = nginx.read_text()
    mutations = (
        safe_nginx.replace("    access_log off;\n", ""),
        safe_nginx.replace("    access_log off;\n", "    access_log /tmp/chat-access.log;\n"),
        safe_nginx.replace(
            "    access_log off;\n", "    access_log off;\n    access_log /tmp/chat-access.log;\n"
        ),
        safe_nginx.replace("    error_log /dev/null emerg;\n", "", 1),
        safe_nginx.replace(
            "    error_log /dev/null emerg;\n", "    error_log /tmp/chat-error.log;\n", 1
        ),
        safe_nginx.replace(
            "    auth_request /_penge_chat_auth;",
            "    auth_request /_penge_chat_auth;\n    error_page 401 = /oauth2/sign_in;",
        ),
    )

    for mutated in mutations:
        assert mutated != safe_nginx
        nginx.write_text(mutated)
        rejected = subprocess.run(  # noqa: S603  # Temporary validator copy under test.
            [validator, "--ready"], capture_output=True, check=False, env=env, text=True
        )
        assert rejected.returncode != 0
        assert "disable chat API and auth logging and redirects" in rejected.stderr


def test_ready_validator_rejects_quadlet_boot_activation(tmp_path: Path) -> None:
    validator, env = _ready_validator_fixture(tmp_path)
    quadlet = validator.parent / "penge-chat.container.in"
    quadlet.write_text(f"{quadlet.read_text()}\n[Install]\nWantedBy=default.target\n")
    rejected = subprocess.run(  # noqa: S603  # Temporary validator copy under test.
        [validator, "--ready"], capture_output=True, check=False, env=env, text=True
    )
    assert rejected.returncode != 0
    assert "must not enable boot activation" in rejected.stderr


def test_ready_validator_rejects_published_tcp_and_mismatched_socket(tmp_path: Path) -> None:
    validator, env = _ready_validator_fixture(tmp_path)
    quadlet = validator.parent / "penge-chat.container.in"
    safe = quadlet.read_text()
    quadlet.write_text(f"{safe}\nPublishPort=127.0.0.1:8123:3000\n")
    published = subprocess.run(  # noqa: S603  # Temporary validator copy under test.
        [validator, "--ready"], capture_output=True, check=False, env=env, text=True
    )
    assert published.returncode != 0
    assert "must not publish TCP ports" in published.stderr
    quadlet.write_text(safe.replace("/srv/penge/chat-socket", "/srv/penge/other"))
    mismatch = subprocess.run(  # noqa: S603  # Temporary validator copy under test.
        [validator, "--ready"], capture_output=True, check=False, env=env, text=True
    )
    assert mismatch.returncode != 0
    assert "socket path must match" in mismatch.stderr


def test_ready_validator_rejects_overlong_host_socket_path(tmp_path: Path) -> None:
    validator, env = _ready_validator_fixture(tmp_path)
    quadlet = validator.parent / "penge-chat.container.in"
    quadlet.write_text(quadlet.read_text().replace("/srv/penge/chat-socket", f"/srv/{'a' * 100}"))
    rejected = subprocess.run(  # noqa: S603  # Temporary validator copy under test.
        [validator, "--ready"], capture_output=True, check=False, env=env, text=True
    )
    assert rejected.returncode != 0
    assert "socket path exceeds the Unix socket length limit" in rejected.stderr


def test_ready_validator_rejects_host_network_and_privileged_role(
    tmp_path: Path,
) -> None:
    validator, env = _ready_validator_fixture(tmp_path)
    quadlet = validator.parent / "penge-chat.container.in"
    database = validator.parent / "penge-chat-db-role.sql.in"
    safe_database = database.read_text()

    quadlet.write_text(quadlet.read_text().replace("Network=private-ask", "Network=host"))
    host_network = subprocess.run(  # noqa: S603  # Temporary validator copy under test.
        [validator, "--ready"],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )
    quadlet.write_text(quadlet.read_text().replace("Network=host", "Network=private-ask"))
    database.write_text(
        safe_database.replace(
            (
                "CREATE ROLE penge_chat_oauth LOGIN NOSUPERUSER NOCREATEDB "
                "NOCREATEROLE NOINHERIT NOBYPASSRLS;"
            ),
            "CREATE ROLE penge_chat_oauth LOGIN SUPERUSER;",
        )
    )
    privileged_role = subprocess.run(  # noqa: S603
        # Temporary validator copy under test.
        [validator, "--ready"],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )
    database.write_text(
        safe_database.replace(
            "CREATE ROLE penge_chat_oauth LOGIN",
            "CREATE ROLE another_chat_role LOGIN",
        )
    )
    mismatched_role = subprocess.run(  # noqa: S603
        # Temporary validator copy under test.
        [validator, "--ready"],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )

    assert host_network.returncode != 0
    assert "dedicated non-host rootless network" in host_network.stderr
    assert privileged_role.returncode != 0
    assert "explicitly deny privileged and inherited attributes" in privileged_role.stderr
    assert mismatched_role.returncode != 0
    assert "created chat role and database grant target differ" in mismatched_role.stderr


_SAFE_ROLE_CREATION = (
    "CREATE ROLE penge_chat_oauth LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS"
)
_SYNTHETIC_SCRAM = "'SCRAM-SHA-256$4096:c3ludGhldGlj$c3RvcmVk:c2VydmVy'"


@pytest.mark.parametrize(
    "password_clause",
    [
        "PASSWORD 'plaintext'",
        f"PASSWORD {_SYNTHETIC_SCRAM}REPLICATION",
        "PASSWORD 'x'IN/**/ROLE/**/pg_write_all_data",
        f"PASSWORD {_SYNTHETIC_SCRAM}/**/CONNECTION/**/LIMIT/**/-1",
        "PASSWORD NULL",
    ],
)
def test_ready_validator_rejects_role_options_smuggled_through_password(
    tmp_path: Path, password_clause: str
) -> None:
    validator, env = _ready_validator_fixture(tmp_path)
    database = validator.parent / "penge-chat-db-role.sql.in"
    database.write_text(
        database.read_text().replace(
            f"{_SAFE_ROLE_CREATION};", f"{_SAFE_ROLE_CREATION} {password_clause};"
        )
    )

    rejected = subprocess.run(  # noqa: S603  # Temporary validator copy under test.
        [validator, "--ready"], capture_output=True, check=False, env=env, text=True
    )

    assert rejected.returncode != 0
    assert "explicitly deny privileged and inherited attributes" in rejected.stderr


def test_ready_validator_allows_role_password_as_scram_verifier(tmp_path: Path) -> None:
    validator, env = _ready_validator_fixture(tmp_path)
    database = validator.parent / "penge-chat-db-role.sql.in"
    database.write_text(
        database.read_text().replace(
            f"{_SAFE_ROLE_CREATION};", f"{_SAFE_ROLE_CREATION} PASSWORD {_SYNTHETIC_SCRAM};"
        )
    )

    accepted = subprocess.run(  # noqa: S603  # Temporary validator copy under test.
        [validator, "--ready"], capture_output=True, check=False, env=env, text=True
    )

    assert "explicitly deny privileged and inherited attributes" not in accepted.stderr
    assert "exact approved database privilege shape" not in accepted.stderr
    assert "requires reviewed container connectivity and isolation evidence" in accepted.stderr


def test_ready_validator_rejects_shared_or_migration_database_credential(
    tmp_path: Path,
) -> None:
    validator, env = _ready_validator_fixture(tmp_path)
    quadlet = validator.parent / "penge-chat.container.in"
    safe_quadlet = quadlet.read_text()

    quadlet.write_text(
        safe_quadlet.replace(
            "/run/secrets/finance-mcp-database-url",
            "/run/secrets/chat-database-url",
        )
    )
    shared = subprocess.run(  # noqa: S603  # Temporary validator copy under test.
        [validator, "--ready"],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )
    quadlet.write_text(
        f"{safe_quadlet}Secret=penge-chat-migration-database-url-v1,"
        "type=mount,target=/run/secrets/migration-database-url\n"
    )
    migration = subprocess.run(  # noqa: S603  # Temporary validator copy under test.
        [validator, "--ready"],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )

    assert shared.returncode != 0
    assert "assignment does not match its secret target" in shared.stderr
    assert migration.returncode != 0
    assert "migration-owner database credential" in migration.stderr


def test_ready_validator_requires_external_https_api_base_with_trailing_slash(
    tmp_path: Path,
) -> None:
    validator, env = _ready_validator_fixture(tmp_path)
    contract = validator.parent / "private-ask-chat.contract.env.in"
    contract.write_text(
        contract.read_text().replace(
            "https://chat.example.test/ask/api/",
            "https://chat.example.test/ask/api",
        )
    )

    invalid_base = subprocess.run(  # noqa: S603  # Temporary validator copy under test.
        [validator, "--ready"],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )

    assert invalid_base.returncode != 0
    assert "must preserve the /ask/api/ callback prefix" in invalid_base.stderr


def test_ready_validator_rejects_unsafe_resolved_security_assignment(
    tmp_path: Path,
) -> None:
    validator, env = _ready_validator_fixture(tmp_path)
    contract = validator.parent / "private-ask-chat.contract.env.in"
    contract.write_text(
        contract.read_text().replace(
            "PENGE_MODEL_FALLBACK=false",
            "PENGE_MODEL_FALLBACK=true",
        )
    )

    unsafe = subprocess.run(  # noqa: S603  # Temporary validator copy under test.
        [validator, "--ready"],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )

    assert unsafe.returncode != 0
    assert "resolved security assignments violate" in unsafe.stderr


def test_ready_validator_parses_effective_sdk_dependency_and_instructions(
    tmp_path: Path,
) -> None:
    validator, env = _ready_validator_fixture(tmp_path)
    repo = validator.parents[2]
    package = repo / "apps" / "chat" / "package.json"
    containerfile = repo / "apps" / "chat" / "Containerfile"

    package.write_text(
        '{"metadata":{"@github/copilot-sdk":"1.0.16"},'
        '"dependencies":{"@github/copilot-sdk":"^1.0.16"}}\n'
    )
    mutable_sdk = subprocess.run(  # noqa: S603  # Temporary validator copy under test.
        [validator, "--ready"],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )
    package.write_text('{"dependencies":{"@github/copilot-sdk":"1.0.16"}}\n')
    containerfile.write_text(
        f"FROM node@sha256:{'a' * 64}\n"
        "# COPY pnpm-lock.yaml ./\n"
        "# RUN pnpm install --frozen-lockfile\n"
    )
    commented_packaging = subprocess.run(  # noqa: S603
        # Temporary validator copy under test.
        [validator, "--ready"],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )

    assert mutable_sdk.returncode != 0
    assert "must pin @github/copilot-sdk exactly to 1.0.16" in mutable_sdk.stderr
    assert commented_packaging.returncode != 0
    assert "does not COPY pnpm-lock.yaml" in commented_packaging.stderr


def test_ready_validator_rejects_missing_sdk_lock_entries(tmp_path: Path) -> None:
    validator, env = _ready_validator_fixture(tmp_path)
    lockfile = validator.parents[2] / "pnpm-lock.yaml"
    lockfile.write_text("lockfileVersion: '9.0'\nimporters: {}\n")

    stale_lock = subprocess.run(  # noqa: S603  # Temporary validator copy under test.
        [validator, "--ready"],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )

    assert stale_lock.returncode != 0
    assert "does not freeze the apps/chat Copilot SDK dependency" in stale_lock.stderr


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
    signature = approval.with_suffix(f"{approval.suffix}.sig")
    signature.unlink(missing_ok=True)
    subprocess.run(  # noqa: S603  # Fixed system SSH signing binary under test.
        [
            SSH_KEYGEN,
            "-Y",
            "sign",
            "-f",
            str(repo / "synthetic-reviewer"),
            "-n",
            "penge-private-ask-chat-approval",
            str(approval),
        ],
        capture_output=True,
        check=True,
        text=True,
    )
    signature.chmod(0o600)
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
    reviewer_key = repo / "synthetic-reviewer"
    subprocess.run(  # noqa: S603  # Fixed system SSH key generator for synthetic data.
        [SSH_KEYGEN, "-q", "-t", "ed25519", "-N", "", "-f", reviewer_key],
        capture_output=True,
        check=True,
        text=True,
    )
    trusted_reviewers = tmp_path / "private-ask-chat-reviewers.allowed_signers"
    trusted_reviewers.write_text(
        f"synthetic-reviewer {reviewer_key.with_suffix('.pub').read_text()}"
    )
    installer.write_text(
        installer.read_text().replace(
            "/etc/penge/private-ask-chat-reviewers.allowed_signers",
            str(trusted_reviewers),
        )
    )
    template = _read("penge-chat.container.in")
    if resolved:
        socket_dir = tmp_path / "socket"
        socket_dir.mkdir()
        socket_dir.chmod(0o2750)
        nginx_template = nas / "penge-chat.nginx.conf.in"
        nginx_template.write_text(
            nginx_template.read_text().replace("@@CHAT_SOCKET_HOST_DIR@@", str(socket_dir))
        )
        replacements = {
            "@@CHAT_CONTAINER_GID@@": "1000",
            "@@CHAT_CONTAINER_UID@@": "1000",
            "@@CHAT_HEALTH_COMMAND@@": "/usr/bin/true",
            "@@CHAT_HEALTH_START_PERIOD@@": "10s",
            "@@CHAT_SOCKET_HOST_DIR@@": str(socket_dir),
            "@@CHAT_SOCKET_VOLUME_OPTIONS@@": "rw",
            "@@CHAT_ROOTLESS_NETWORK@@": "private-ask",
            "@@DATABASE_URL_SECRET_TARGET@@": "/run/secrets/chat-database-url",
            "@@DATABASE_URL_SECRET_VERSION@@": "v1",
            "@@FINANCE_MCP_DATABASE_URL_SECRET_TARGET@@": ("/run/secrets/finance-mcp-database-url"),
            "@@FINANCE_MCP_DATABASE_URL_SECRET_VERSION@@": "v1",
            "@@GITHUB_CLIENT_SECRET_TARGET@@": "/run/secrets/github-client-secret",
            "@@GITHUB_CLIENT_SECRET_VERSION@@": "v1",
            "@@IDENTITY_PEPPER_SECRET_TARGET@@": "/run/secrets/identity-pepper",
            "@@IDENTITY_PEPPER_SECRET_VERSION@@": "v1",
            "@@MCP_READ_ONLY_SOURCE@@": "/srv/penge/mcp",
            "@@MCP_READ_ONLY_TARGET@@": "/app/mcp",
            "@@PROXY_SECRET_TARGET@@": "/run/secrets/proxy-secret",
            "@@PROXY_SECRET_VERSION@@": "v1",
            "@@TOKEN_KEYRING_SECRET_TARGET@@": "/run/secrets/token-keyring",
            "@@TOKEN_KEYRING_SECRET_VERSION@@": "v1",
        }
        for token, value in replacements.items():
            template = template.replace(token, value)
    (nas / "penge-chat.container.in").write_text(template)
    contract_template = nas / "private-ask-chat.contract.env.in"
    if resolved:
        contract_template.write_text(_resolved_contract_environment())
    contract = contract_dir / "private-ask-chat.contract.env"
    contract.write_text(
        contract_template.read_text() if resolved else "PENGE_CHAT_MODEL=hydrafusion\n"
    )
    contract.chmod(0o600)
    _write_approval_manifest(repo, home, "a" * 64)

    _write_executable(
        fake_bin / "id",
        '#!/bin/sh\nprintf "%s\\n" "$FAKE_ID_UID"\n',
    )
    _write_executable(
        fake_bin / "podman",
        """#!/bin/sh
if [ "$1 $2" = "network exists" ]; then
  exit 0
fi
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
if [ "$3" = "$TRUSTED_REVIEWERS_FILE" ] && [ "$1 $2" = "-c %u %a" ]; then
  printf "0 644\\n"
  exit 0
fi
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
        "FAKE_ID_UID": str(os.getuid()),
        "SYSTEMCTL_LOG": str(tmp_path / "systemctl.log"),
        "TRUSTED_REVIEWERS_FILE": str(trusted_reviewers),
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
    contract_template = installer.parent / "private-ask-chat.contract.env.in"
    resolved_contract = _resolved_contract_environment()
    contract_template.write_text(resolved_contract)
    contract.write_text(resolved_contract)
    _write_approval_manifest(installer.parents[2], Path(env["HOME"]), digest)
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


def test_installer_requires_exact_resolved_environment_contract(tmp_path: Path) -> None:
    installer, env = _installer_fixture(tmp_path, resolved=True)
    digest = "a" * 64
    home = Path(env["HOME"])
    contract = home / ".config" / "penge" / "private-ask-chat.contract.env"
    contract.write_text(contract.read_text().replace("PENGE_MODEL_FALLBACK=false\n", ""))
    _write_approval_manifest(installer.parents[2], home, digest)

    incomplete = subprocess.run(  # noqa: S603  # Temporary installer copy under test.
        [installer, digest],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )

    assert incomplete.returncode != 0
    assert "contract environment is not the exact reviewed template" in incomplete.stderr


def test_installer_rejects_locally_rehashed_unsigned_approval(tmp_path: Path) -> None:
    installer, env = _installer_fixture(tmp_path, resolved=True)
    digest = "a" * 64
    repo = installer.parents[2]
    home = Path(env["HOME"])
    contract = home / ".config" / "penge" / "private-ask-chat.contract.env"
    contract_template = repo / "deploy" / "nas" / "private-ask-chat.contract.env.in"
    approval = home / ".config" / "penge" / "private-ask-chat.approval.manifest"
    changed_contract = f"{contract.read_text()}PENGE_SYNTHETIC_REVIEW_BYPASS=true\n"
    contract.write_text(changed_contract)
    contract_template.write_text(changed_contract)
    contract_hash = _sha256(contract)
    quadlet = repo / "deploy" / "nas" / "penge-chat.container.in"
    rendered = (
        quadlet.read_text()
        .replace("@@CHAT_IMAGE_DIGEST@@", digest)
        .replace("@@CONTRACT_ENV_SHA256@@", contract_hash)
    )
    manifest = approval.read_text()
    replacements = {
        "contract_env_sha256": contract_hash,
        "contract_env_template_sha256": _sha256(contract_template),
        "rendered_quadlet_sha256": hashlib.sha256(rendered.encode()).hexdigest(),
    }
    for key, value in replacements.items():
        manifest = re.sub(
            rf"^{key}=.*$",
            f"{key}={value}",
            manifest,
            flags=re.MULTILINE,
        )
    approval.write_text(manifest)

    forged = subprocess.run(  # noqa: S603  # Temporary installer copy under test.
        [installer, digest],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )

    assert forged.returncode != 0
    assert "lacks a trusted reviewer signature" in forged.stderr


def test_installer_rejects_approved_host_network_or_migration_secret(
    tmp_path: Path,
) -> None:
    installer, env = _installer_fixture(tmp_path, resolved=True)
    digest = "a" * 64
    home = Path(env["HOME"])
    quadlet = installer.parent / "penge-chat.container.in"
    safe_quadlet = quadlet.read_text()
    quadlet.write_text(safe_quadlet.replace("Network=private-ask", "Network=host"))
    _write_approval_manifest(installer.parents[2], home, digest)

    host_network = subprocess.run(  # noqa: S603  # Temporary installer copy under test.
        [installer, digest],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )
    quadlet.write_text(
        f"{safe_quadlet}Secret=penge-chat-migration-database-url-v1,"
        "type=mount,target=/run/secrets/migration-database-url\n"
    )
    _write_approval_manifest(installer.parents[2], home, digest)
    migration = subprocess.run(  # noqa: S603  # Temporary installer copy under test.
        [installer, digest],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )

    assert host_network.returncode != 0
    assert "dedicated non-host rootless network" in host_network.stderr
    assert migration.returncode != 0
    assert "migration-owner credential" in migration.stderr


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
    assert f"contract environment must be owned by uid {os.getuid()}" in wrong_owner.stderr


def test_installer_requires_concrete_approving_review_url(tmp_path: Path) -> None:
    installer, env = _installer_fixture(tmp_path, resolved=True)
    digest = "a" * 64
    approval = Path(env["HOME"]) / ".config" / "penge" / "private-ask-chat.approval.manifest"
    original = approval.read_text()

    for invalid_reference in (
        "https://github.com/autoditac/Penge/issues/342",
        "https://github.com/autoditac/Penge/pull/347",
        "https://github.com/autoditac/Penge/pull/347#arbitrary",
    ):
        approval.write_text(
            re.sub(
                r"^review_reference=.*$",
                f"review_reference={invalid_reference}",
                original,
                flags=re.MULTILINE,
            )
        )
        rejected = subprocess.run(  # noqa: S603  # Temporary installer copy under test.
            [installer, digest],
            capture_output=True,
            check=False,
            env=env,
            text=True,
        )
        assert rejected.returncode != 0
        assert "invalid approval review reference" in rejected.stderr


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
    contract.write_text((repo / "deploy" / "nas" / "private-ask-chat.contract.env.in").read_text())
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
    assert "contract environment is not the exact reviewed template" in changed_contract.stderr
    assert "approval hash mismatch for quadlet_template_sha256" in changed_template.stderr


def test_installer_rejects_signed_quadlet_with_boot_activation(tmp_path: Path) -> None:
    installer, env = _installer_fixture(tmp_path, resolved=True)
    repo = installer.parents[2]
    template = installer.parent / "penge-chat.container.in"
    template.write_text(f"{template.read_text()}\n[Install]\nWantedBy=default.target\n")
    _write_approval_manifest(repo, Path(env["HOME"]), "a" * 64)

    rejected = subprocess.run(  # noqa: S603  # Temporary installer copy under test.
        [installer, "a" * 64], capture_output=True, check=False, env=env, text=True
    )
    assert rejected.returncode != 0
    assert "must not enable boot activation" in rejected.stderr
    assert not (tmp_path / "systemctl.log").exists()


def test_installer_rejects_unsafe_socket_directory_and_existing_path(tmp_path: Path) -> None:
    installer, env = _installer_fixture(tmp_path, resolved=True)
    socket_dir = tmp_path / "socket"
    socket_dir.chmod(0o2770)
    unsafe = subprocess.run(  # noqa: S603  # Temporary installer copy under test.
        [installer, "a" * 64], capture_output=True, check=False, env=env, text=True
    )
    socket_dir.chmod(0o2750)
    (socket_dir / "chat.sock").write_text("synthetic")
    existing = subprocess.run(  # noqa: S603  # Temporary installer copy under test.
        [installer, "a" * 64], capture_output=True, check=False, env=env, text=True
    )
    assert unsafe.returncode != 0
    assert existing.returncode != 0
    assert "socket directory ownership, mode, or existing path is unsafe" in unsafe.stderr
    assert "socket directory ownership, mode, or existing path is unsafe" in existing.stderr
    assert not (tmp_path / "systemctl.log").exists()


def test_installer_rejects_writable_socket_host_ancestor(tmp_path: Path) -> None:
    installer, env = _installer_fixture(tmp_path, resolved=True)
    tmp_path.chmod(0o770)
    try:
        rejected = subprocess.run(  # noqa: S603  # Temporary installer copy under test.
            [installer, "a" * 64], capture_output=True, check=False, env=env, text=True
        )
    finally:
        tmp_path.chmod(0o700)
    assert rejected.returncode != 0
    assert "socket directory has an unsafe host ancestor" in rejected.stderr
    assert not (tmp_path / "systemctl.log").exists()


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
        env={**env, "XDG_CONFIG_HOME": str(tmp_path / "custom-xdg")},
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
    assert not (tmp_path / "custom-xdg").exists()
    assert unit.read_text().count("Image=") == 1
    assert f"@sha256:{digest}" in unit.read_text()
    assert (tmp_path / "systemctl.log").read_text().strip() == "--user daemon-reload"


def test_installer_uses_approved_snapshot_if_source_changes_during_install(tmp_path: Path) -> None:
    installer, env = _installer_fixture(tmp_path, resolved=True)
    original = Path(env["HOME"]) / ".config" / "penge" / "private-ask-chat.contract.env"
    approved_bytes = original.read_bytes()
    fake_podman = Path(env["PATH"].split(os.pathsep)[0]) / "podman"
    _write_executable(
        fake_podman,
        '#!/bin/sh\nif [ "$1 $2" = "network exists" ]; then\n'
        '  printf "PENGE_CHAT_MODEL=unapproved\\n" >"$CONTRACT_SOURCE"\nfi\nexit 0\n',
    )

    installed = subprocess.run(  # noqa: S603  # Temporary installer copy under test.
        [installer, "a" * 64],
        capture_output=True,
        check=False,
        env={**env, "CONTRACT_SOURCE": str(original)},
        text=True,
    )
    assert installed.returncode == 0, installed.stderr
    assert original.read_bytes() != approved_bytes
    unit_dir = Path(env["HOME"]) / ".config" / "containers" / "systemd"
    contracts = list((Path(env["HOME"]) / ".config" / "penge" / "approved").glob("*.env"))
    assert len(contracts) == 1
    assert contracts[0].read_bytes() == approved_bytes
    assert _sha256(contracts[0]) in (unit_dir / "penge-chat.container").read_text()
