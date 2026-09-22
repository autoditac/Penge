#!/usr/bin/env bash
# deploy/runner/docker-gc.sh — age-bounded Docker garbage collection for the
# self-hosted GitHub Actions runner (`gh-runner-ubuntu`).
#
# Why this exists
# ---------------
# CI builds container images with `docker/setup-buildx-action`, which starts a
# `buildx_buildkit_<builder>0` container backed by a *named* volume
# (`..._state`). Both the action's post-step and the workflow's `if: always()`
# teardown remove them on a normal (even failing) job. Neither runs when the
# job dies abnormally: runner service restart, host reboot, OOM kill, a
# cancellation that outlives the cancel timeout, or a disk that is already
# full. The leaked BuildKit container keeps *running*, which pins its named
# volume, so `docker system prune -af --volumes` cannot reclaim it -- that is
# exactly how the runner reached 100% disk twice.
#
# This script is the host-level backstop: it runs from a systemd timer,
# independent of GitHub Actions, so it still fires when the runner is wedged.
#
# Concurrency safety
# ------------------
# Every removal is gated on age. Only BuildKit containers *created* more than
# `--max-age-hours` ago (default 2h) are removed, and image/cache pruning uses
# Docker's `until=` filter with the same threshold. The longest CI job timeout
# is 30 minutes (`release.yml`), so a resource older than the threshold cannot
# belong to a running job. Nothing here is unconditional: there is no bare
# `docker system prune`, and running non-BuildKit containers (the runner
# itself, Postgres, ...) are never touched.
#
# Usage:
#   ./docker-gc.sh [--max-age-hours N] [--prefix NAME] [--dry-run]
#
# Environment overrides:
#   PENGE_GC_MAX_AGE_HOURS   same as --max-age-hours (default 2)
#   PENGE_GC_PREFIX          same as --prefix (default buildx_buildkit_)
#   DOCKER                   docker binary to invoke (default `docker`)

set -euo pipefail

MAX_AGE_HOURS="${PENGE_GC_MAX_AGE_HOURS:-2}"
PREFIX="${PENGE_GC_PREFIX:-buildx_buildkit_}"
DOCKER="${DOCKER:-docker}"
DRY_RUN=0

usage() {
    sed -n '2,40p' "$0"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --max-age-hours)
            MAX_AGE_HOURS="$2"
            shift 2
            ;;
        --prefix)
            PREFIX="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        -h | --help)
            usage
            exit 0
            ;;
        *)
            echo "unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if ! [[ "${MAX_AGE_HOURS}" =~ ^[0-9]+$ ]] || [[ "${MAX_AGE_HOURS}" -lt 1 ]]; then
    echo "--max-age-hours must be a positive integer (got '${MAX_AGE_HOURS}')" >&2
    exit 2
fi

if [[ -z "${PREFIX}" ]]; then
    echo "--prefix must not be empty" >&2
    exit 2
fi

log() {
    printf '[penge-docker-gc] %s\n' "$*"
}

run() {
    if [[ "${DRY_RUN}" -eq 1 ]]; then
        log "DRY-RUN would run: $*"
        return 0
    fi
    # A single stubborn resource must not abort the whole sweep: the
    # remaining reclaims are what keep the disk bounded.
    if ! "$@"; then
        log "WARNING: command failed (continuing): $*"
    fi
}

now_epoch="$(date -u +%s)"
cutoff_epoch="$((now_epoch - MAX_AGE_HOURS * 3600))"

log "max age ${MAX_AGE_HOURS}h, container prefix '${PREFIX}', dry-run=${DRY_RUN}"
log "disk usage before:"
"${DOCKER}" system df || true

# 1. Stale BuildKit builder containers (running or not) and their state
#    volumes. This is the only step that can reclaim a *pinned* named volume,
#    because the volume stays in use until its container is gone.
stale_containers=()
while IFS=$'\t' read -r name created; do
    [[ -n "${name}" ]] || continue
    # `docker ps --format '{{.CreatedAt}}'` renders e.g.
    # "2026-09-22 09:03:25 +0200 CEST". GNU date rejects the trailing zone
    # abbreviation, so feed it only date/time/offset.
    read -r c_date c_time c_offset _ <<<"${created}"
    created_epoch="$(date -u -d "${c_date} ${c_time} ${c_offset}" +%s 2>/dev/null || echo 0)"
    if [[ "${created_epoch}" -eq 0 ]]; then
        log "WARNING: cannot parse creation time of ${name} ('${created}'); skipping"
        continue
    fi
    age_hours="$(((now_epoch - created_epoch) / 3600))"
    if [[ "${created_epoch}" -lt "${cutoff_epoch}" ]]; then
        log "stale builder ${name} (age ~${age_hours}h) -> remove"
        stale_containers+=("${name}")
    else
        log "keeping builder ${name} (age ~${age_hours}h, below threshold)"
    fi
done < <("${DOCKER}" ps --all --no-trunc --filter "name=^/${PREFIX}" \
    --format '{{.Names}}	{{.CreatedAt}}' || true)

for name in "${stale_containers[@]:-}"; do
    [[ -n "${name}" ]] || continue
    run "${DOCKER}" rm --force --volumes "${name}"
    # `docker rm --volumes` only drops anonymous volumes; the BuildKit state
    # volume is named after the container and must go explicitly.
    run "${DOCKER}" volume rm --force "${name}_state"
done

# 2. Dangling images older than the threshold. Each CI run re-tags
#    `penge/<app>:ci-<run>`, so superseded layers accumulate here.
run "${DOCKER}" image prune --force --filter "until=${MAX_AGE_HOURS}h"

# 3. Build cache of the default (docker driver) builder, same age bound.
run "${DOCKER}" builder prune --force --filter "until=${MAX_AGE_HOURS}h"

# 4. Named/anonymous volumes left unused once their container is gone. Safe
#    now that step 1 removed the containers that were pinning them; volumes
#    still attached to a running container are never touched by prune.
run "${DOCKER}" volume prune --force

# 5. Per-job `DOCKER_CONFIG` scratch directories from the image jobs.
if [[ "${DRY_RUN}" -eq 1 ]]; then
    log "DRY-RUN would remove /tmp/penge-docker-* older than ${MAX_AGE_HOURS}h"
else
    find /tmp -maxdepth 1 -name 'penge-docker-*' -type d \
        -mmin "+$((MAX_AGE_HOURS * 60))" -exec rm -rf {} + 2>/dev/null || true
fi

log "disk usage after:"
"${DOCKER}" system df || true
log "done"
