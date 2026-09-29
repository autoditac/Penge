#!/usr/bin/env bash
# deploy/runner/workspace-gc.sh — age-bounded cleanup of the self-hosted GitHub
# Actions runner's *own* working directories on `gh-runner-ubuntu`.
#
# Why this exists
# ---------------
# `docker-gc.sh` bounds Docker's growth, but Docker was never the whole story.
# The host runs three runner instances on a 19 GB root filesystem, and a survey
# taken while CI was failing at 92% full found Docker holding only 3.7 GB while
# `/var/lib/ghrunner` held 7.4 GB. Two things dominate that, and neither is
# reclaimed by anything that ships with the runner:
#
# * `_work/_update` — the staging payload the runner unpacks when it upgrades
#   itself. It is left behind afterwards and never reused: 678 MB per runner,
#   ~2 GB across three, duplicating `externals.<version>/` byte for byte.
# * `_diag/` — runner and worker logs. They accumulate for the life of the
#   host; ~394 MB across three runners here.
#
# Concurrency safety
# ------------------
# Same contract as `docker-gc.sh`: every removal is gated on modification time,
# with a default threshold (2 h) well beyond the longest CI job timeout
# (30 min, `release.yml`). A self-update takes seconds, so an `_update`
# directory untouched for hours provably belongs to a finished upgrade.
#
# `_work/<owner>/<repo>` checkouts are deliberately **not** touched. A runner
# reuses them across jobs, so deleting one only forces a fresh clone -- and an
# age check cannot prove a long-running job is not about to write there.
#
# Usage:
#   ./workspace-gc.sh [--root DIR] [--max-age-hours N]
#                     [--diag-retention-days N] [--dry-run]
#
# Environment overrides:
#   PENGE_GC_RUNNER_ROOT     same as --root (default /var/lib/ghrunner)
#   PENGE_GC_MAX_AGE_HOURS   same as --max-age-hours (default 2)
#   PENGE_GC_DIAG_DAYS       same as --diag-retention-days (default 7)

set -euo pipefail

RUNNER_ROOT="${PENGE_GC_RUNNER_ROOT:-/var/lib/ghrunner}"
MAX_AGE_HOURS="${PENGE_GC_MAX_AGE_HOURS:-2}"
DIAG_DAYS="${PENGE_GC_DIAG_DAYS:-7}"
DRY_RUN=0

usage() {
    sed -n '2,38p' "$0"
}

require_value() {
    # `set -u` would abort with status 1 on a missing operand, hiding the
    # documented "invalid arguments" exit status 2. An operand that looks like
    # an option is rejected too: swallowing `--dry-run` as the value of
    # `--root` would turn a rehearsal into a destructive sweep.
    if [[ $# -lt 2 ]] || [[ "$2" == -* ]]; then
        echo "$1 requires a value" >&2
        exit 2
    fi
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --root)
            require_value "$@"
            RUNNER_ROOT="$2"
            shift 2
            ;;
        --max-age-hours)
            require_value "$@"
            MAX_AGE_HOURS="$2"
            shift 2
            ;;
        --diag-retention-days)
            require_value "$@"
            DIAG_DAYS="$2"
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

if ! [[ "${DIAG_DAYS}" =~ ^[0-9]+$ ]] || [[ "${DIAG_DAYS}" -lt 1 ]]; then
    echo "--diag-retention-days must be a positive integer (got '${DIAG_DAYS}')" >&2
    exit 2
fi

if [[ ! -d "${RUNNER_ROOT}" ]]; then
    echo "runner root '${RUNNER_ROOT}' does not exist" >&2
    exit 2
fi

log() {
    printf '[penge-workspace-gc] %s\n' "$*" >&2
}

remove() {
    local target="$1"
    if [[ "${DRY_RUN}" -eq 1 ]]; then
        log "DRY-RUN would remove ${target}"
        return 0
    fi
    rm -rf -- "${target}"
}

disk_usage() {
    df -h "${RUNNER_ROOT}" | tail -n 1
}

max_age_minutes="$((MAX_AGE_HOURS * 60))"

log "root ${RUNNER_ROOT}, max age ${MAX_AGE_HOURS}h, diag retention ${DIAG_DAYS}d, dry-run=${DRY_RUN}"
log "disk before: $(disk_usage)"

shopt -s nullglob

for runner_dir in "${RUNNER_ROOT}"/*/; do
    runner="$(basename "${runner_dir}")"

    # A directory is only a runner if it has the layout we expect. Anything
    # else under the root -- a backup, someone's scratch dir -- is left alone.
    [[ -d "${runner_dir}_work" ]] || continue

    # 1. Self-update staging payload. Present only after an upgrade, never
    #    read again, and a byte-for-byte duplicate of `externals.<version>/`.
    update_dir="${runner_dir}_work/_update"
    if [[ -d "${update_dir}" ]]; then
        # `-mmin +N` on the directory itself: the runner touches it while
        # unpacking, so an untouched one cannot be an upgrade in flight.
        if [[ -n "$(find "${update_dir}" -maxdepth 0 -mmin "+${max_age_minutes}" 2>/dev/null)" ]]; then
            log "stale self-update payload ${runner}/_work/_update -> remove"
            remove "${update_dir}"
        else
            log "keeping ${runner}/_work/_update (below age threshold)"
        fi
    fi

    # 2. Runner and worker logs. These are the only record of what a job did
    #    once the Actions-side logs expire, so they get a retention window in
    #    days rather than the job-scale threshold used everywhere else.
    diag_dir="${runner_dir}_diag"
    if [[ -d "${diag_dir}" ]]; then
        while IFS= read -r -d '' logfile; do
            log "stale diag log ${logfile#"${RUNNER_ROOT}"/} -> remove"
            remove "${logfile}"
        done < <(find "${diag_dir}" -type f -name '*.log' -mtime "+${DIAG_DAYS}" -print0 2>/dev/null)
    fi

    # 3. Per-job temp files. The runner clears `_work/_temp` at the start of a
    #    job, so anything older than the threshold belongs to a job that died
    #    before cleanup.
    temp_dir="${runner_dir}_work/_temp"
    if [[ -d "${temp_dir}" ]]; then
        while IFS= read -r -d '' leftover; do
            log "stale temp entry ${leftover#"${RUNNER_ROOT}"/} -> remove"
            remove "${leftover}"
        done < <(find "${temp_dir}" -mindepth 1 -maxdepth 1 -mmin "+${max_age_minutes}" -print0 2>/dev/null)
    fi
done

log "disk after: $(disk_usage)"
log "done"
