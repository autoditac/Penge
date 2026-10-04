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
config_home="${XDG_CONFIG_HOME:-$HOME/.config}"
unit_dir="$config_home/containers/systemd"
contract_dir="$config_home/penge"
contract_env="$contract_dir/private-ask-chat.contract.env"
approval="$contract_dir/private-ask-chat.contract-approved"
target="$unit_dir/penge-chat.container"

if [[ ! -r $contract_env || ! -r $approval ]]; then
  echo "deployment blocked: reviewed contract env and approval marker are required" >&2
  exit 1
fi

umask 077
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
sed "s/@@CHAT_IMAGE_DIGEST@@/$1/g" "$template" >"$tmp"

if grep -n '@@[A-Z0-9_]\+@@' "$tmp" >&2; then
  echo "deployment blocked: unresolved private Ask contract tokens" >&2
  exit 1
fi

if grep -Eq 'Image=.*:(main|latest)([[:space:]]|$)' "$tmp" \
  || ! grep -q '^PublishPort=127\.0\.0\.1:8123:' "$tmp"; then
  echo "deployment blocked: mutable image or non-loopback publish detected" >&2
  exit 1
fi

while IFS= read -r secret; do
  podman secret exists "$secret" || {
    echo "deployment blocked: missing rootless Podman secret $secret" >&2
    exit 1
  }
done < <(sed -n 's/^Secret=\([^,]*\),.*/\1/p' "$tmp")

install -d -m 0700 "$unit_dir"
install -m 0600 "$tmp" "$target"
systemctl --user daemon-reload
echo "rendered $target; inspect it before explicitly enabling the user service"
