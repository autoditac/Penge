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

for path in \
  "$quadlet" \
  "$nginx_template" \
  "$db_template" \
  "$contract_env_template" \
  "$nginx_live"; do
  [[ -r $path ]] || {
    echo "missing deployment seam: $path" >&2
    exit 1
  }
done

[[ ! -e "$root/deploy/nas/penge-chat.container" ]] || {
  echo "deployable chat Quadlet must not exist before contracts are resolved" >&2
  exit 1
}

if grep -Eq 'Image=.*:(main|latest)([[:space:]]|$)|AutoUpdate=registry' "$quadlet"; then
  echo "chat image must be immutable and must not auto-update by tag" >&2
  exit 1
fi
grep -q '^Image=.*@sha256:@@CHAT_IMAGE_DIGEST@@$' "$quadlet"
grep -q '^PublishPort=127\.0\.0\.1:8123:' "$quadlet"
! grep -Eq '^PublishPort=(0\.0\.0\.0:|\[::\]:)' "$quadlet"
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
grep -q 'OAUTH_LINK_TABLES_ONLY' "$db_template"
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
  [[ -n $unresolved ]] || {
    echo "seam mode requires fail-closed unresolved contracts" >&2
    exit 1
  }
  echo "private Ask deployment seam is fail-closed; deployment is not ready"
  exit 0
fi

image_digest="${PENGE_CHAT_IMAGE_DIGEST:-}"
if [[ ! $image_digest =~ ^[0-9a-f]{64}$ ]]; then
  echo "deployment blocked: PENGE_CHAT_IMAGE_DIGEST must be an exact 64-character digest" >&2
  exit 1
fi

unresolved="$(grep -v '^@@CHAT_IMAGE_DIGEST@@$' <<<"$unresolved" || true)"
if [[ -n $unresolved ]]; then
  printf 'deployment blocked by unresolved contracts:\n%s\n' "$unresolved" >&2
  exit 1
fi

for path in "$root/apps/chat/package.json" "$root/apps/chat/Containerfile"; do
  [[ -r $path ]] || {
    echo "deployment blocked: missing backend packaging contract $path" >&2
    exit 1
  }
done

containerfile="$root/apps/chat/Containerfile"
grep -Eq '^FROM .+@sha256:[0-9a-f]{64}' "$containerfile"
grep -q 'pnpm-lock.yaml' "$containerfile"
grep -q -- '--frozen-lockfile' "$containerfile"
grep -Eq \
  '"@github/copilot-sdk"[[:space:]]*:[[:space:]]*"1\.0\.16"' \
  "$root/apps/chat/package.json"
grep -Eq 'app:[[:space:]]*\[[^]]*chat' "$root/.github/workflows/ci.yml"
grep -Eq 'app:[[:space:]]*\[[^]]*chat' "$root/.github/workflows/release.yml"
echo "private Ask deployment contracts are resolved and packaging is ready"
