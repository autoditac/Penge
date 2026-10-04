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
! grep -q 'SecurityLabelDisable' "$quadlet"
! grep -Eq '^Volume=.*chat.*:rw([,:]|$)' "$quadlet"
grep -q '^WantedBy=default.target$' "$quadlet"
grep -q 'systemctl --user daemon-reload' "$root/deploy/nas/install-private-ask-chat-quadlet.sh"
! grep -Eq 'sudo|/etc/containers/systemd|systemctl daemon-reload' \
  "$root/deploy/nas/install-private-ask-chat-quadlet.sh"

grep -q 'location = /ask {' "$nginx_live"
grep -q 'location ^~ /ask/ {' "$nginx_live"
! grep -q 'proxy_pass http://127.0.0.1:8123' "$nginx_live"
grep -q 'return 404;' "$nginx_live"
grep -q 'location = /ask {' "$nginx_template"
grep -q 'location ^~ /ask/ {' "$nginx_template"
! grep -Eq 'script-src[^;]*unsafe-inline' "$nginx_template"
grep -q 'proxy_set_header X-Forwarded-User      $user;' "$nginx_template"
grep -q 'proxy_set_header X-Forwarded-Email     $email;' "$nginx_template"
grep -q 'proxy_set_header X-Forwarded-Client-Id $email;' "$nginx_template"

sql_body="$(sed '/^[[:space:]]*--/d' "$db_template")"
! grep -Eiq 'grant[[:space:]]+all|analytics|finance|transcript|default privileges' \
  <<<"$sql_body"
grep -q 'REVOKE ALL ON SCHEMA public FROM PUBLIC;' "$db_template"
! grep -q '@@DATABASE_IDENTIFIER@@' "$db_template"
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
  grep -q '@@CHAT_UPSTREAM_WITH_EXPLICIT_BASE_PATH_SEMANTICS@@' "$nginx_template"
  grep -q "current_database() <> '@@CHAT_OAUTH_DATABASE_NAME@@'" "$db_template"
  grep -q \
    'REVOKE ALL ON DATABASE "@@CHAT_OAUTH_DATABASE_NAME@@" FROM PUBLIC;' \
    "$db_template"
  grep -q '@@OAUTH_LINK_TABLES_ONLY@@' "$db_template"
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

[[ ${publish_lines[0]} =~ ^PublishPort=127\.0\.0\.1:8123:[0-9]{1,5}$ ]] \
  || fail "resolved publish must remain loopback-only with a numeric container port"
container_port="${publish_lines[0]##*:}"
((container_port >= 1 && container_port <= 65535)) \
  || fail "resolved container port is outside the valid range"

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

for path in "$root/apps/chat/package.json" "$root/apps/chat/Containerfile"; do
  [[ -r $path ]] || fail "missing backend packaging contract $path"
done

containerfile="$root/apps/chat/Containerfile"
validate_containerfile_bases "$containerfile"
grep -q 'pnpm-lock.yaml' "$containerfile"
grep -q -- '--frozen-lockfile' "$containerfile"
grep -Eq \
  '"@github/copilot-sdk"[[:space:]]*:[[:space:]]*"1\.0\.16"' \
  "$root/apps/chat/package.json"
grep -Eq 'app:[[:space:]]*\[[^]]*chat' "$root/.github/workflows/ci.yml"
grep -Eq 'app:[[:space:]]*\[[^]]*chat' "$root/.github/workflows/release.yml"
echo "private Ask deployment contracts are resolved and packaging is ready"
