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

require_value() {
    # `set -u` would abort with status 1 on a missing operand, hiding the
    # documented "invalid arguments" exit status 2. A value that looks like
    # an option is also rejected: silently swallowing `--dry-run` as the
    # operand of `--prefix` would turn a rehearsal into a destructive sweep.
    if [[ $# -lt 2 ]] || [[ "$2" == -* ]]; then
        echo "$1 requires a value" >&2
        exit 2
    fi
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --max-age-hours)
            require_value "$@"
            MAX_AGE_HOURS="$2"
            shift 2
            ;;
        --prefix)
            require_value "$@"
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

# `docker ps`/`docker images --format '{{.CreatedAt}}'` render e.g.
# "2026-09-22 09:03:25 +0200 CEST"; GNU date rejects the trailing zone
# abbreviation, so feed it only date/time/offset. `docker volume inspect`
# renders RFC 3339, which date parses as-is. Echoes 0 when unparseable.
created_epoch_of() {
    local created="$1"
    # RFC 3339 (docker volume inspect): parse as-is. Anchor on the date+`T`
    # shape -- a naive `*T*` match also hits the "... +0000 UTC" suffix of
    # `docker ps` timestamps.
    if [[ "${created}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T ]]; then
        date -u -d "${created}" +%s 2>/dev/null || echo 0
        return 0
    fi
    local c_date c_time c_offset _rest
    read -r c_date c_time c_offset _rest <<<"${created}"
    date -u -d "${c_date} ${c_time} ${c_offset}" +%s 2>/dev/null || echo 0
}

# Echoes the names (one per line) of resources older than the cutoff, given
# `name<TAB>timestamp` lines on stdin. Keeping the age gate in one place is
# what makes "never touch a concurrent job's resources" auditable.
select_stale() {
    local kind="$1" name created created_epoch age_hours
    while IFS=$'\t' read -r name created; do
        [[ -n "${name}" ]] || continue
        created_epoch="$(created_epoch_of "${created}")"
        if [[ "${created_epoch}" -eq 0 ]]; then
            log "WARNING: cannot parse creation time of ${kind} ${name} ('${created}'); skipping" >&2
            continue
        fi
        age_hours="$(((now_epoch - created_epoch) / 3600))"
        if [[ "${created_epoch}" -lt "${cutoff_epoch}" ]]; then
            log "stale ${kind} ${name} (age ~${age_hours}h) -> remove" >&2
            printf '%s\n' "${name}"
        else
            log "keeping ${kind} ${name} (age ~${age_hours}h, below threshold)" >&2
        fi
    done
}

log "max age ${MAX_AGE_HOURS}h, container prefix '${PREFIX}', dry-run=${DRY_RUN}"
log "disk usage before:"
"${DOCKER}" system df || true

# 1. Stale BuildKit builder containers (running or not) and their state
#    volumes. This is the only step that can reclaim a *pinned* named volume,
#    because the volume stays in use until its container is gone.
mapfile -t stale_containers < <(
    "${DOCKER}" ps --all --no-trunc --filter "name=^/${PREFIX}" \
        --format '{{.Names}}	{{.CreatedAt}}' 2>/dev/null |
        select_stale builder
)

for name in "${stale_containers[@]:-}"; do
    [[ -n "${name}" ]] || continue
    run "${DOCKER}" rm --force --volumes "${name}"
    # `docker rm --volumes` only drops anonymous volumes; the BuildKit state
    # volume is named after the container and must go explicitly.
    run "${DOCKER}" volume rm --force "${name}_state"
done

# 2. Stale CI images. These are *tagged* (`penge/<app>:ci-<run>-<attempt>`),
#    so `docker image prune` -- which only removes dangling images -- would
#    never reclaim the image of a job killed before its teardown ran. Match
#    the tag pattern explicitly and gate on age, rather than reaching for
#    `--all`, which would also delete images that nothing in CI produced.
mapfile -t stale_images < <(
    "${DOCKER}" images --filter 'reference=penge/*:ci-*' \
        --format '{{.Repository}}:{{.Tag}}	{{.CreatedAt}}' 2>/dev/null |
        select_stale image
)

for image in "${stale_images[@]:-}"; do
    [[ -n "${image}" ]] || continue
    run "${DOCKER}" image rm --force "${image}"
done

# 3. Dangling images older than the threshold (superseded intermediate and
#    untagged layers).
run "${DOCKER}" image prune --force --filter "until=${MAX_AGE_HOURS}h"

# 4. Build cache of the default (docker driver) builder, same age bound.
run "${DOCKER}" builder prune --force --filter "until=${MAX_AGE_HOURS}h"

# 5. BuildKit state volumes orphaned by a container removed elsewhere.
#    `docker volume prune` supports no `until` filter, and a blanket prune
#    would be unbounded in age -- it could take an anonymous volume a
#    concurrent job has created but not yet attached. Enumerate instead, so
#    the age gate still holds.
mapfile -t dangling_volumes < <(
    "${DOCKER}" volume ls --quiet --filter dangling=true \
        --filter "name=${PREFIX}" 2>/dev/null | while read -r volume; do
        [[ -n "${volume}" ]] || continue
        created="$("${DOCKER}" volume inspect --format '{{.CreatedAt}}' "${volume}" 2>/dev/null || true)"
        [[ -n "${created}" ]] && printf '%s\t%s\n' "${volume}" "${created}"
    done | select_stale volume
)

for volume in "${dangling_volumes[@]:-}"; do
    [[ -n "${volume}" ]] || continue
    run "${DOCKER}" volume rm --force "${volume}"
done

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
