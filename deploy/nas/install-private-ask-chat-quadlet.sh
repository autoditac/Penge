#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: $0 <64-character image digest without sha256:>" >&2
}

if [[ $# -ne 1 || ! $1 =~ ^[0-9a-f]{64}$ ]]; then
  usage
  exit 2
fi

if [[ $(id -u) -eq 0 ]]; then
  echo "refusing root execution: the chat Quadlet is rootless" >&2
  exit 1
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
template="$root/deploy/nas/penge-chat.container.in"
nginx_template="$root/deploy/nas/penge-chat.nginx.conf.in"
database_template="$root/deploy/nas/penge-chat-db-role.sql.in"
contract_env_template="$root/deploy/nas/private-ask-chat.contract.env.in"
config_home="$HOME/.config"
unit_dir="$config_home/containers/systemd"
contract_dir="$config_home/penge"
approved_dir="$contract_dir/approved"
contract_env="$contract_dir/private-ask-chat.contract.env"
approval="$contract_dir/private-ask-chat.approval.manifest"
approval_signature="$approval.sig"
trusted_reviewers="/etc/penge/private-ask-chat-reviewers.allowed_signers"
target="$unit_dir/penge-chat.container"

runtime_uid="$(id -u)"

validate_private_file() {
  local path=$1
  local label=$2
  local owner mode

  if [[ ! -f $path || -L $path || ! -r $path ]]; then
    echo "deployment blocked: $label must be a readable regular file" >&2
    exit 1
  fi
  read -r owner mode < <(stat -c '%u %a' "$path")
  if [[ $owner != "$runtime_uid" ]]; then
    echo "deployment blocked: $label must be owned by uid $runtime_uid" >&2
    exit 1
  fi
  if [[ $mode != "400" && $mode != "600" ]]; then
    echo "deployment blocked: $label must use mode 0400 or 0600" >&2
    exit 1
  fi
}

sha256_file() {
  local hash
  read -r hash _ < <(sha256sum "$1")
  printf '%s\n' "$hash"
}

validate_private_file "$contract_env" "contract environment"
validate_private_file "$approval" "approval manifest"
validate_private_file "$approval_signature" "approval signature"
if [[ ! -f $trusted_reviewers || -L $trusted_reviewers || ! -r $trusted_reviewers ]]; then
  echo "deployment blocked: trusted reviewer keys must be a readable regular file" >&2
  exit 1
fi
read -r trusted_owner trusted_mode < <(stat -c '%u %a' "$trusted_reviewers")
if [[ $trusted_owner != "0" || ($trusted_mode != "444" && $trusted_mode != "644") ]]; then
  echo "deployment blocked: trusted reviewer keys must be root-owned mode 0444 or 0644" >&2
  exit 1
fi

declare -A approved=()
while IFS='=' read -r key value || [[ -n $key$value ]]; do
  case "$key" in
    version | decision | reviewed_by | review_reference | image_digest \
      | contract_env_sha256 | quadlet_template_sha256 \
      | rendered_quadlet_sha256 | nginx_template_sha256 \
      | database_template_sha256 | contract_env_template_sha256) ;;
    *)
      echo "deployment blocked: unknown or malformed approval key $key" >&2
      exit 1
      ;;
  esac
  if [[ -z $value || -n ${approved[$key]+present} ]]; then
    echo "deployment blocked: empty or duplicate approval key $key" >&2
    exit 1
  fi
  approved[$key]=$value
done <"$approval"

required_keys=(
  version
  decision
  reviewed_by
  review_reference
  image_digest
  contract_env_sha256
  quadlet_template_sha256
  rendered_quadlet_sha256
  nginx_template_sha256
  database_template_sha256
  contract_env_template_sha256
)
for key in "${required_keys[@]}"; do
  if [[ -z ${approved[$key]+present} ]]; then
    echo "deployment blocked: missing approval key $key" >&2
    exit 1
  fi
done

if [[ ${approved[version]} != "1" || ${approved[decision]} != "approved" ]]; then
  echo "deployment blocked: approval decision is not an approved v1 manifest" >&2
  exit 1
fi
if [[ ! ${approved[reviewed_by]} =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,38}$ ]]; then
  echo "deployment blocked: invalid approval reviewer" >&2
  exit 1
fi
if [[ ! ${approved[review_reference]} =~ ^https://github\.com/autoditac/Penge/pull/[0-9]+#pullrequestreview-[0-9]+$ ]]; then
  echo "deployment blocked: invalid approval review reference" >&2
  exit 1
fi
if [[ ${approved[image_digest]} != "$1" ]]; then
  echo "deployment blocked: image digest is not approved" >&2
  exit 1
fi
if ! ssh-keygen -Y verify \
  -f "$trusted_reviewers" \
  -I "${approved[reviewed_by]}" \
  -n "penge-private-ask-chat-approval" \
  -s "$approval_signature" <"$approval"; then
  echo "deployment blocked: approval manifest lacks a trusted reviewer signature" >&2
  exit 1
fi

if grep -n '@@[A-Z0-9_]\+@@' "$contract_env" >&2; then
  echo "deployment blocked: unresolved private Ask environment tokens" >&2
  exit 1
fi
if ! cmp -s "$contract_env_template" "$contract_env"; then
  echo "deployment blocked: contract environment is not the exact reviewed template" >&2
  exit 1
fi

contract_env_sha256="$(sha256_file "$contract_env")"
declare -A expected_hashes=(
  [contract_env_sha256]="$contract_env_sha256"
  [quadlet_template_sha256]="$(sha256_file "$template")"
  [nginx_template_sha256]="$(sha256_file "$nginx_template")"
  [database_template_sha256]="$(sha256_file "$database_template")"
  [contract_env_template_sha256]="$(sha256_file "$contract_env_template")"
)
for key in "${!expected_hashes[@]}"; do
  if [[ ${approved[$key]} != "${expected_hashes[$key]}" ]]; then
    echo "deployment blocked: approval hash mismatch for $key" >&2
    exit 1
  fi
done

umask 077
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
sed \
  -e "s/@@CHAT_IMAGE_DIGEST@@/$1/g" \
  -e "s/@@CONTRACT_ENV_SHA256@@/$contract_env_sha256/g" \
  "$template" >"$tmp"

if grep -n '@@[A-Z0-9_]\+@@' "$tmp" >&2; then
  echo "deployment blocked: unresolved private Ask contract tokens" >&2
  exit 1
fi

mapfile -t image_lines < <(grep '^Image=' "$tmp" || true)
expected_image="Image=ghcr.io/autoditac/penge/chat@sha256:$1"
if [[ ${#image_lines[@]} -ne 1 || ${image_lines[0]} != "$expected_image" ]]; then
  echo "deployment blocked: exactly one immutable chat image is required" >&2
  exit 1
fi

mapfile -t publish_lines < <(grep '^PublishPort=' "$tmp" || true)
if [[ ${#publish_lines[@]} -ne 1 ]] \
  || [[ ! ${publish_lines[0]} =~ ^PublishPort=127\.0\.0\.1:8123:[0-9]{1,5}$ ]]; then
  echo "deployment blocked: exactly one loopback-only publish is required" >&2
  exit 1
fi
container_port="${publish_lines[0]##*:}"
if ((container_port < 1 || container_port > 65535)); then
  echo "deployment blocked: container port is outside the valid range" >&2
  exit 1
fi
mapfile -t network_lines < <(grep '^Network=' "$tmp" || true)
if [[ ${#network_lines[@]} -ne 1 ]]; then
  echo "deployment blocked: exactly one rootless chat network is required" >&2
  exit 1
fi
network="${network_lines[0]#Network=}"
if [[ ! $network =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$ ]]; then
  echo "deployment blocked: invalid rootless chat network name" >&2
  exit 1
fi
case "${network,,}" in
  host | none | bridge | default | podman)
    echo "deployment blocked: a dedicated non-host rootless network is required" >&2
    exit 1
    ;;
esac
if ! podman network exists "$network"; then
  echo "deployment blocked: missing rootless Podman network $network" >&2
  exit 1
fi
if grep -Eiq \
  'PENGE_CHAT_MIGRATION_DATABASE_URL_FILE|migration[^,]*database[^,]*url' \
  "$tmp" "$contract_env"; then
  echo "deployment blocked: migration-owner credential must not enter the runtime container" >&2
  exit 1
fi
runtime_secret_targets=()
validate_runtime_secret() {
  local prefix=$1
  local environment_name=$2
  local target
  local -a secret_lines

  mapfile -t secret_lines < <(grep "^Secret=$prefix-" "$tmp" || true)
  if [[ ${#secret_lines[@]} -ne 1 ]]; then
    echo "deployment blocked: $environment_name secret must appear exactly once" >&2
    exit 1
  fi
  target="$(sed -n 's/.*[,]target=\([^,]*\).*/\1/p' <<<"${secret_lines[0]}")"
  if [[ ! $target =~ ^/run/secrets/[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$ ]]; then
    echo "deployment blocked: $environment_name secret target is invalid" >&2
    exit 1
  fi
  if [[ $(grep -c "^$environment_name=" "$contract_env") -ne 1 \
    || $(sed -n "s/^$environment_name=//p" "$contract_env") != "$target" ]]; then
    echo "deployment blocked: $environment_name must match its secret target" >&2
    exit 1
  fi
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
if [[ $unique_secret_target_count -ne ${#runtime_secret_targets[@]} ]]; then
  echo "deployment blocked: every runtime credential needs a distinct mounted file" >&2
  exit 1
fi

rendered_quadlet_sha256="$(sha256_file "$tmp")"
if [[ ${approved[rendered_quadlet_sha256]} != "$rendered_quadlet_sha256" ]]; then
  echo "deployment blocked: approval hash mismatch for rendered_quadlet_sha256" >&2
  exit 1
fi

while IFS= read -r secret; do
  podman secret exists "$secret" || {
    echo "deployment blocked: missing rootless Podman secret $secret" >&2
    exit 1
  }
done < <(sed -n 's/^Secret=\([^,]*\),.*/\1/p' "$tmp")

install -d -m 0700 "$approved_dir"
install -d -m 0700 "$unit_dir"
install -m 0600 \
  "$contract_env" \
  "$approved_dir/private-ask-chat.contract-$contract_env_sha256.env"
install -m 0600 "$tmp" "$target"
systemctl --user daemon-reload
echo "rendered $target; inspect it before explicitly enabling the user service"
