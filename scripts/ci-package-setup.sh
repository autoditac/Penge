#!/usr/bin/env bash
# Coordinate repository-owned system package installers on the shared CI host.
set -euo pipefail
export LC_ALL=C

if [[ "$#" == 0 ]]; then
    echo "Usage: ci-package-setup.sh COMMAND [ARG...]" >&2
    exit 2
fi

lock_dir="${HOME:?}/.cache/penge-ci"
mkdir -p "$lock_dir"
exec 9>"$lock_dir/package-setup.lock"
if ! flock --exclusive --timeout 300 9; then
    echo "Timed out waiting for the host package installer (300s)." >&2
    exit 75
fi

log="$(mktemp)"
trap 'rm -f "$log"' EXIT

# Other host package managers do not take our advisory lock. Retry only apt's
# explicit lock failures, never repository, network or package-script failures.
for attempt in 1 2 3; do
    if "$@" >"$log" 2>&1; then
        cat "$log"
        exit 0
    else
        status=$?
    fi
    cat "$log" >&2
    if ! grep -q '^E: Could not get lock ' "$log"; then
        exit "$status"
    fi
    if [[ "$attempt" == 3 ]]; then
        echo "Package-manager lock contention persisted after 3 attempts." >&2
        exit "$status"
    fi
    echo "Package-manager lock contention; retrying in 10s (attempt $attempt/3)." >&2
    sleep 10
done
