#!/usr/bin/env bash
set -euo pipefail

mode="${1:---seam}"
if [[ $mode != "--seam" && $mode != "--ready" ]]; then
  echo "usage: $0 [--seam|--ready]" >&2
  exit 2
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
quadlet="$root/deploy/nas/penge-chat.container.in"
nginx_template="$root/deploy/nas/penge-chat.nginx.conf.in"
db_template="$root/deploy/nas/penge-chat-db-role.sql.in"
contract_env_template="$root/deploy/nas/private-ask-chat.contract.env.in"
nginx_live="$root/deploy/nas/penge.eigmueller.de.conf"

fail() {
  echo "deployment blocked: $*" >&2
  exit 1
}

validate_containerfile_bases() {
  local containerfile=$1
  local line source stage i
  local -a fields
  local source_index from_count=0
  declare -A stages=()

  while IFS= read -r line; do
    read -r -a fields <<<"$line"
    ((${#fields[@]} >= 2)) || fail "chat Containerfile has a malformed FROM directive"
    source_index=1
    while ((source_index < ${#fields[@]})) \
      && [[ ${fields[$source_index]} == --* ]]; do
      ((source_index += 1))
    done
    ((source_index < ${#fields[@]})) \
      || fail "chat Containerfile has a malformed FROM directive"
    source="${fields[$source_index]}"
    ((from_count += 1))
    if [[ $source != "scratch" && -z ${stages[$source]+present} ]] \
      && [[ ! $source =~ @sha256:[0-9a-f]{64}$ ]]; then
      fail "external base image is not digest-pinned: $source"
    fi
    stage=""
    for ((i = source_index + 1; i < ${#fields[@]}; i += 1)); do
      if [[ ${fields[$i],,} == "as" && $((i + 1)) -lt ${#fields[@]} ]]; then
        stage="${fields[$((i + 1))]}"
        break
      fi
    done
    if [[ -n $stage ]]; then
      stages[$stage]=1
    fi
  done < <(grep -Ei '^[[:space:]]*FROM[[:space:]]+' "$containerfile" || true)

  ((from_count > 0)) || fail "chat Containerfile has no FROM directive"
}

for path in \
  "$quadlet" \
  "$nginx_template" \
  "$db_template" \
  "$contract_env_template" \
  "$nginx_live"; do
  [[ -r $path ]] || fail "missing deployment seam $path"
done

[[ ! -e "$root/deploy/nas/penge-chat.container" ]] \
  || fail "deployable chat Quadlet must not be tracked"

if grep -Eq 'Image=.*:(main|latest)([[:space:]]|$)|AutoUpdate=registry' "$quadlet"; then
  fail "chat image must be immutable and must not auto-update by tag"
fi
mapfile -t image_lines < <(grep '^Image=' "$quadlet" || true)
[[ ${#image_lines[@]} -eq 1 ]] || fail "exactly one chat image directive is required"
[[ ${image_lines[0]} == \
  "Image=ghcr.io/autoditac/penge/chat@sha256:@@CHAT_IMAGE_DIGEST@@" ]] \
  || fail "chat image template is not the immutable GHCR reference"
mapfile -t publish_lines < <(grep '^PublishPort=' "$quadlet" || true)
[[ ${#publish_lines[@]} -eq 1 ]] || fail "exactly one chat publish directive is required"
mapfile -t network_lines < <(grep '^Network=' "$quadlet" || true)
[[ ${#network_lines[@]} -eq 1 ]] || fail "exactly one chat network directive is required"
if grep -q 'SecurityLabelDisable' "$quadlet"; then
  fail "chat Quadlet must retain default SELinux confinement"
fi
if grep -Eq '^Volume=.*chat.*:rw([,:]|$)' "$quadlet"; then
  fail "chat Quadlet must not persist transcripts"
fi
if grep -Eiq \
  'PENGE_CHAT_MIGRATION_DATABASE_URL_FILE|migration[^,]*database[^,]*url' \
  "$quadlet"; then
  fail "migration-owner database credential must not enter the runtime container"
fi
grep -q '^WantedBy=default.target$' "$quadlet"
grep -q 'systemctl --user daemon-reload' "$root/deploy/nas/install-private-ask-chat-quadlet.sh"
if grep -Eq 'sudo|/etc/containers/systemd|systemctl daemon-reload' \
  "$root/deploy/nas/install-private-ask-chat-quadlet.sh"; then
  fail "chat installer must remain rootless"
fi

grep -q 'location = /ask {' "$nginx_live"
grep -q 'location ^~ /ask/ {' "$nginx_live"
if grep -q 'proxy_pass http://127.0.0.1:8123' "$nginx_live"; then
  fail "live nginx must not activate the unresolved chat upstream"
fi
grep -q 'return 404;' "$nginx_live"
grep -q 'location ^~ /ask/api/ {' "$nginx_template"
if grep -Eq '^location[[:space:]]+(=[[:space:]]+/ask|\^~[[:space:]]+/ask/)[[:space:]]*\{' \
  "$nginx_template"; then
  fail "chat nginx template must leave /ask frontend routing to the web SPA"
fi
grep -q 'proxy_pass http://127.0.0.1:8123/;' "$nginx_template"
if grep -Eq 'script-src[^;]*unsafe-inline' "$nginx_template"; then
  fail "chat CSP must not allow inline scripts"
fi
grep -q 'proxy_set_header x-penge-auth-issuer ' "$nginx_template"
grep -q 'proxy_set_header x-penge-auth-subject ' "$nginx_template"
grep -q 'proxy_set_header x-penge-proxy-secret ' "$nginx_template"
if grep -Eiq 'X-Forwarded-(User|Email|Client-Id)' "$nginx_template"; then
  fail "chat nginx template must not forward mutable identity headers"
fi

sql_body="$(sed '/^[[:space:]]*--/d' "$db_template")"
if grep -Eiq \
  'grant[[:space:]]+all|analytics|finance|transcript|default privileges' \
  <<<"$sql_body"; then
  fail "chat database template exceeds the OAuth-only privilege boundary"
fi
grant_count="$(grep -Eic '^[[:space:]]*GRANT[[:space:]]' <<<"$sql_body")"
revoke_count="$(grep -Eic '^[[:space:]]*REVOKE[[:space:]]' <<<"$sql_body")"
[[ $grant_count -eq 5 && $revoke_count -eq 4 ]] \
  || fail "chat database template has an unexpected GRANT or REVOKE shape"
[[ $(grep -Eic '^[[:space:]]*ON TABLE([[:space:]]|$)' <<<"$sql_body") -eq 2 ]] \
  || fail "chat database template must grant exactly two table groups"
[[ $(grep -Eic '^[[:space:]]*ON SEQUENCE([[:space:]]|$)' <<<"$sql_body") -eq 1 ]] \
  || fail "chat database template must grant exactly one sequence"
grep -q 'REVOKE ALL ON SCHEMA public FROM PUBLIC;' "$db_template"
if grep -q '@@DATABASE_IDENTIFIER@@' "$db_template"; then
  fail "chat database template uses an unguarded database identifier"
fi
grep -q '^PENGE_CHAT_MODEL=hydrafusion$' "$contract_env_template"

unresolved="$(
  grep -hEo '@@[A-Z0-9_]+@@' \
    "$quadlet" \
    "$nginx_template" \
    "$db_template" \
    "$contract_env_template" \
    | sort -u || true
)"

if [[ $mode == "--seam" ]]; then
  [[ ${publish_lines[0]} == "PublishPort=127.0.0.1:8123:@@CHAT_HTTP_PORT@@" ]] \
    || fail "unresolved seam publish contract changed unexpectedly"
  [[ ${network_lines[0]} == "Network=@@CHAT_ROOTLESS_NETWORK@@" ]] \
    || fail "unresolved seam network contract changed unexpectedly"
  grep -q '@@IMMUTABLE_AUTH_SUBJECT_NGINX_VALUE@@' "$nginx_template"
  grep -q '@@TRUSTED_PROXY_ISSUER_NGINX_VALUE@@' "$nginx_template"
  grep -q '@@MOUNTED_PROXY_SECRET_NGINX_VALUE@@' "$nginx_template"
  grep -q "current_database() <> '@@CHAT_OAUTH_DATABASE_NAME@@'" "$db_template"
  grep -q \
    'REVOKE ALL ON DATABASE "@@CHAT_OAUTH_DATABASE_NAME@@" FROM PUBLIC;' \
    "$db_template"
  grep -q '@@OAUTH_LINK_SCHEMA@@.chat_oauth_link' "$db_template"
  grep -q '@@OAUTH_LINK_SCHEMA@@.chat_oauth_state' "$db_template"
  grep -q '@@OAUTH_LINK_SCHEMA@@.chat_audit_event' "$db_template"
  grep -q '@@OAUTH_LINK_SCHEMA@@.chat_audit_event_id_seq' "$db_template"
  grep -q '@@COPILOT_MODE_EMPTY_ENV_ASSIGNMENT@@' "$contract_env_template"
  [[ -n $unresolved ]] || fail "seam mode requires fail-closed unresolved contracts"
  echo "private Ask deployment seam is fail-closed; deployment is not ready"
  exit 0
fi

image_digest="${PENGE_CHAT_IMAGE_DIGEST:-}"
[[ $image_digest =~ ^[0-9a-f]{64}$ ]] \
  || fail "PENGE_CHAT_IMAGE_DIGEST must be an exact 64-character digest"

unresolved="$(
  grep -v -E '^@@(CHAT_IMAGE_DIGEST|CONTRACT_ENV_SHA256)@@$' <<<"$unresolved" || true
)"
if [[ -n $unresolved ]]; then
  printf 'deployment blocked by unresolved contracts:\n%s\n' "$unresolved" >&2
  exit 1
fi
if ! uv run --no-project python - "$contract_env_template" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
lines = path.read_text().splitlines()
expected_markers = {
    "copilot-mode": "empty",
    "model-fallback": "false",
    "hydrafusion-entitlement-required": "true",
    "source-coverage-required": "true",
    "mcp-transport": "stdio",
    "default-tools-enabled": "false",
    "transcript-persistence": "false",
    "structured-logging": "redacted",
    "metrics": "private",
}
assignments: dict[str, str] = {}
marker_assignments: dict[str, tuple[str, str]] = {}
pending_marker: str | None = None
for line in lines:
    stripped = line.strip()
    marker = re.fullmatch(r"# security-contract: ([a-z-]+)=([a-z]+)", stripped)
    if marker:
        name, documented_value = marker.groups()
        if name not in expected_markers or documented_value != expected_markers[name]:
            raise SystemExit(f"invalid security marker: {stripped}")
        if name in marker_assignments or pending_marker is not None:
            raise SystemExit(f"duplicate or unbound security marker: {name}")
        pending_marker = name
        continue
    if not stripped or stripped.startswith("#"):
        continue
    if "=" not in stripped:
        raise SystemExit(f"invalid environment assignment: {stripped}")
    key, value = stripped.split("=", 1)
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or key in assignments:
        raise SystemExit(f"invalid or duplicate environment key: {key}")
    assignments[key] = value
    if pending_marker is not None:
        marker_assignments[pending_marker] = (key, value)
        pending_marker = None
if pending_marker is not None:
    raise SystemExit(f"unbound security marker: {pending_marker}")
if set(marker_assignments) != set(expected_markers):
    raise SystemExit("security contract assignments are incomplete")
for marker_name, (_, value) in marker_assignments.items():
    if value != expected_markers[marker_name]:
        raise SystemExit(
            f"unsafe {marker_name} value: expected {expected_markers[marker_name]}"
        )
PY
then
  fail "resolved security assignments violate the fixed architecture contract"
fi

[[ ${publish_lines[0]} =~ ^PublishPort=127\.0\.0\.1:8123:[0-9]{1,5}$ ]] \
  || fail "resolved publish must remain loopback-only with a numeric container port"
container_port="${publish_lines[0]##*:}"
((container_port >= 1 && container_port <= 65535)) \
  || fail "resolved container port is outside the valid range"
network="${network_lines[0]#Network=}"
[[ $network =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$ ]] \
  || fail "resolved rootless network name is invalid"
case "${network,,}" in
  host | none | bridge | default | podman)
    fail "resolved chat network must be a dedicated non-host rootless network"
    ;;
esac
if grep -q '^PENGE_CHAT_MIGRATION_DATABASE_URL_FILE=' "$contract_env_template"; then
  fail "migration-owner database credential must not enter the runtime environment"
fi
runtime_secret_targets=()
validate_runtime_secret() {
  local prefix=$1
  local environment_name=$2
  local target
  local -a secret_lines

  mapfile -t secret_lines < <(grep "^Secret=$prefix-" "$quadlet" || true)
  [[ ${#secret_lines[@]} -eq 1 ]] \
    || fail "$environment_name secret must appear exactly once"
  target="$(sed -n 's/.*[,]target=\([^,]*\).*/\1/p' <<<"${secret_lines[0]}")"
  [[ $target =~ ^/run/secrets/[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$ ]] \
    || fail "$environment_name secret target is invalid"
  [[ $(grep -c "^$environment_name=" "$contract_env_template") -eq 1 ]] \
    || fail "$environment_name assignment must appear exactly once"
  [[ $(sed -n "s/^$environment_name=//p" "$contract_env_template") == "$target" ]] \
    || fail "$environment_name assignment does not match its secret target"
  runtime_secret_targets+=("$target")
}

validate_runtime_secret "penge-chat-github-client-secret" \
  "PENGE_CHAT_GITHUB_CLIENT_SECRET_FILE"
validate_runtime_secret "penge-chat-token-keyring" \
  "PENGE_CHAT_TOKEN_KEYRING_FILE"
validate_runtime_secret "penge-chat-identity-pepper" \
  "PENGE_CHAT_IDENTITY_PEPPER_FILE"
validate_runtime_secret "penge-chat-proxy-secret" \
  "PENGE_CHAT_PROXY_SHARED_SECRET_FILE"
validate_runtime_secret "penge-chat-database-url" \
  "PENGE_CHAT_DATABASE_URL_FILE"
validate_runtime_secret "penge-chat-finance-mcp-database-url" \
  "PENGE_DB_URL_FILE"
unique_secret_target_count="$(
  printf '%s\n' "${runtime_secret_targets[@]}" | sort -u | wc -l
)"
[[ $unique_secret_target_count -eq ${#runtime_secret_targets[@]} ]] \
  || fail "every runtime credential must use a distinct mounted file"
public_api_base="$(
  sed -n 's/^PENGE_CHAT_PUBLIC_API_BASE=//p' "$contract_env_template"
)"
public_app_origin="$(
  sed -n 's/^PENGE_CHAT_PUBLIC_APP_ORIGIN=//p' "$contract_env_template"
)"
[[ $public_app_origin =~ ^https://[A-Za-z0-9.-]+(:[0-9]{1,5})?$ ]] \
  || fail "public chat app origin must be an external HTTPS origin only"
[[ $public_api_base == "$public_app_origin/ask/api/" ]] \
  || fail "public chat API base must preserve the /ask/api/ callback prefix"

guard_name="$(
  sed -n "s/.*current_database() <> '\\([^']*\\)'.*/\\1/p" "$db_template"
)"
mapfile -t public_revoke_names < <(
  sed -n 's/^REVOKE ALL ON DATABASE "\([^"]*\)" FROM PUBLIC;/\1/p' "$db_template"
)
[[ -n $guard_name && ${#public_revoke_names[@]} -eq 1 ]] \
  || fail "dedicated OAuth database guard or PUBLIC revoke is missing"
[[ ${public_revoke_names[0]} == "$guard_name" ]] \
  || fail "database guard and PUBLIC revoke target differ"
[[ $guard_name =~ ^[a-z_][a-z0-9_]*$ ]] \
  || fail "dedicated OAuth database name is not a safe identifier"
mapfile -t database_statement_names < <(
  sed -n \
    -e 's/^REVOKE ALL ON DATABASE "\([^"]*\)" FROM .*/\1/p' \
    -e 's/^GRANT CONNECT ON DATABASE "\([^"]*\)" TO .*/\1/p' \
    "$db_template"
)
[[ ${#database_statement_names[@]} -eq 3 ]] \
  || fail "dedicated OAuth database privilege statements are incomplete"
for database_name in "${database_statement_names[@]}"; do
  [[ $database_name == "$guard_name" ]] \
    || fail "database guard and privilege target differ"
done
mapfile -t role_creation_lines < <(
  grep -Ei '^CREATE[[:space:]]+ROLE[[:space:]]+' "$db_template" || true
)
[[ ${#role_creation_lines[@]} -eq 1 ]] \
  || fail "exactly one explicit chat role creation statement is required"
role_creation="${role_creation_lines[0]}"
if [[ ! $role_creation =~ ^CREATE[[:space:]]+ROLE[[:space:]]+([a-z_][a-z0-9_]*)[[:space:]]+LOGIN[[:space:]]+NOSUPERUSER[[:space:]]+NOCREATEDB[[:space:]]+NOCREATEROLE[[:space:]]+NOINHERIT[[:space:]]+NOBYPASSRLS([[:space:]]+PASSWORD[[:space:]]+[^[:space:]\;]+)?\;$ ]]; then
  fail "chat role creation must explicitly deny privileged and inherited attributes"
fi
created_role="${BASH_REMATCH[1]}"
connect_role="$(
  sed -n 's/^GRANT CONNECT ON DATABASE "[^"]*" TO \([a-z_][a-z0-9_]*\);/\1/p' \
    "$db_template"
)"
[[ -n $connect_role && $created_role == "$connect_role" ]] \
  || fail "created chat role and database grant target differ"
mapfile -t privilege_roles < <(
  sed -n 's/.* TO \([a-z_][a-z0-9_]*\);/\1/p' "$db_template"
)
[[ ${#privilege_roles[@]} -eq 5 ]] \
  || fail "chat database privilege targets are incomplete"
for privilege_role in "${privilege_roles[@]}"; do
  [[ $privilege_role == "$created_role" ]] \
    || fail "chat database privilege target differs from the created role"
done

for path in "$root/apps/chat/package.json" "$root/apps/chat/Containerfile"; do
  [[ -r $path ]] || fail "missing backend packaging contract $path"
done

containerfile="$root/apps/chat/Containerfile"
validate_containerfile_bases "$containerfile"
container_instructions="$(
  sed -E '/^[[:space:]]*#/d; :join; /\\[[:space:]]*$/ { N; s/\\[[:space:]]*\n/ /; b join; }' \
    "$containerfile"
)"
lock_copy="$(
  grep -Ein \
  '^[[:space:]]*COPY([[:space:]]+--[^[:space:]]+)*[[:space:]]+[^#]*pnpm-lock\.yaml' \
    <<<"$container_instructions" \
    | head -n 1 || true
)"
[[ -n $lock_copy ]] || fail "chat Containerfile does not COPY pnpm-lock.yaml"
frozen_install="$(
  grep -Ein \
    '^[[:space:]]*RUN([[:space:]]+--[^[:space:]]+)*[[:space:]]+([^#]*[;&|][[:space:]]*)?pnpm[[:space:]]+install([[:space:]]|$)[^#]*--frozen-lockfile([[:space:]]|$)' \
    <<<"$container_instructions" \
    | head -n 1 || true
)"
[[ -n $frozen_install ]] || fail "chat Containerfile does not perform a frozen pnpm install"
((10#${lock_copy%%:*} < 10#${frozen_install%%:*})) \
  || fail "chat Containerfile must COPY pnpm-lock.yaml before the frozen install"
[[ -r "$root/pnpm-lock.yaml" ]] || fail "repository pnpm-lock.yaml is missing"
if ! sdk_version="$(
  uv run --no-project python - "$root/apps/chat/package.json" <<'PY'
import json
import sys
from pathlib import Path

package = json.loads(Path(sys.argv[1]).read_text())
dependencies = package.get("dependencies")
if not isinstance(dependencies, dict):
    raise SystemExit("dependencies must be an object")
version = dependencies.get("@github/copilot-sdk")
if not isinstance(version, str):
    raise SystemExit("@github/copilot-sdk must be a runtime dependency")
print(version)
PY
)"; then
  fail "chat package.json is invalid or lacks the Copilot SDK runtime dependency"
fi
[[ $sdk_version == "1.0.16" ]] \
  || fail "chat package.json must pin @github/copilot-sdk exactly to 1.0.16"
if ! uv run --no-project python - "$root/pnpm-lock.yaml" <<'PY'
import re
import sys
from pathlib import Path

lines = Path(sys.argv[1]).read_text().splitlines()
try:
    importers_index = lines.index("importers:")
except ValueError as error:
    raise SystemExit("pnpm lockfile has no importers section") from error

app_index = next(
    (
        index
        for index in range(importers_index + 1, len(lines))
        if lines[index] == "  apps/chat:"
    ),
    None,
)
if app_index is None:
    raise SystemExit("pnpm lockfile has no apps/chat importer")

app_end = next(
    (
        index
        for index in range(app_index + 1, len(lines))
        if lines[index]
        and not lines[index].startswith("    ")
    ),
    len(lines),
)
app_block = "\n".join(lines[app_index + 1 : app_end])
dependency = re.search(
    r"(?m)^    dependencies:\s*$"
    r"(?:(?:\n      .*)*)"
    r"\n      ['\"]?@github/copilot-sdk['\"]?:\s*$"
    r"(?P<body>(?:\n        .*)+)",
    app_block,
)
if dependency is None:
    raise SystemExit("apps/chat importer has no Copilot SDK dependency")
body = dependency.group("body")
specifier = re.search(r"(?m)^        specifier: (.+)$", body)
version = re.search(r"(?m)^        version: (.+)$", body)
if specifier is None or specifier.group(1).strip("'\"") != "1.0.16":
    raise SystemExit("Copilot SDK lockfile specifier is not exactly 1.0.16")
if version is None or not re.fullmatch(
    r"1\.0\.16(?:\([^)]*\))?", version.group(1).strip("'\"")
):
    raise SystemExit("Copilot SDK lockfile resolution is not 1.0.16")
package_entry = re.compile(
    r"^  ['\"]?@github/copilot-sdk@1\.0\.16(?:\([^)]*\))?['\"]?:"
)
if not any(package_entry.match(line) for line in lines):
    raise SystemExit("pnpm lockfile has no Copilot SDK 1.0.16 package resolution")
PY
then
  fail "pnpm lockfile does not freeze the apps/chat Copilot SDK dependency"
fi
grep -Eq 'app:[[:space:]]*\[[^]]*chat' "$root/.github/workflows/ci.yml"
grep -Eq 'app:[[:space:]]*\[[^]]*chat' "$root/.github/workflows/release.yml"
echo "private Ask deployment contracts are resolved and packaging is ready"
