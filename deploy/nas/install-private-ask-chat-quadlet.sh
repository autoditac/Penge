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

if grep -n '@@[A-Z0-9_]\+@@' "$contract_env" >&2; then
  echo "deployment blocked: unresolved private Ask environment tokens" >&2
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
