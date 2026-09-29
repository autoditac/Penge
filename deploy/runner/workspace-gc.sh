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
# Every removal is gated on age, but the top-level mtime of `_update` is *not*
# a sufficient signal: the runner creates that directory once and then writes
# beneath it, which never refreshes the parent. The gate is therefore the
# newest mtime found **anywhere in the tree**, so an upgrade that is still
# extracting -- however slowly -- always looks fresh.
#
# The threshold for it is a day by default, not the job-scale two hours used
# elsewhere: a self-update takes seconds, so a staging tree with no write for
# 24 h is unambiguously abandoned, and nothing is gained by acting sooner.
#
# This script does **not** run as root. It only ever removes files the runner
# itself owns, and running unprivileged means a symlink planted in the runner
# tree cannot redirect a removal outside `--root`. Symlinked runner
# directories are refused outright for the same reason.
#
# Deliberately left alone:
#
# * `_work/<owner>/<repo>` checkouts and `_work/_tool` -- removing them only
#   forces a re-clone or re-download, and an age check cannot prove a
#   long-running job is not about to write there.
# * `_work/_temp` -- not every job on this runner sets `timeout-minutes`, so
#   no age threshold can prove a temp file is orphaned rather than in use.
#   It holds tens of kilobytes; it is not worth the risk.
#
# Usage:
#   ./workspace-gc.sh [--root DIR] [--update-age-hours N]
#                     [--diag-retention-days N] [--dry-run]
#
# Environment overrides:
#   PENGE_GC_RUNNER_ROOT      same as --root (default /var/lib/ghrunner)
#   PENGE_GC_UPDATE_AGE_HOURS same as --update-age-hours (default 24)
#   PENGE_GC_DIAG_DAYS        same as --diag-retention-days (default 7)

set -euo pipefail

RUNNER_ROOT="${PENGE_GC_RUNNER_ROOT:-/var/lib/ghrunner}"
UPDATE_AGE_HOURS="${PENGE_GC_UPDATE_AGE_HOURS:-24}"
DIAG_DAYS="${PENGE_GC_DIAG_DAYS:-7}"
DRY_RUN=0

usage() {
    sed -n '2,50p' "$0"
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
        --update-age-hours)
            require_value "$@"
            UPDATE_AGE_HOURS="$2"
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

if ! [[ "${UPDATE_AGE_HOURS}" =~ ^[0-9]+$ ]] || [[ "${UPDATE_AGE_HOURS}" -lt 1 ]]; then
    echo "--update-age-hours must be a positive integer (got '${UPDATE_AGE_HOURS}')" >&2
    exit 2
fi

if [[ "$(id -u)" -eq 0 ]]; then
    echo "refusing to run as root: see the comment at the top of this script" >&2
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

update_age_minutes="$((UPDATE_AGE_HOURS * 60))"
# GNU `find -mtime +N` rounds age down to whole days, so `+7` only starts
# matching after eight full days. Convert to minutes so the flag means what
# it says.
diag_age_minutes="$((DIAG_DAYS * 24 * 60))"

log "root ${RUNNER_ROOT}, update age ${UPDATE_AGE_HOURS}h, diag retention ${DIAG_DAYS}d, dry-run=${DRY_RUN}"
log "disk before: $(disk_usage)"

# Newest mtime anywhere in a tree, in epoch seconds. The parent directory's
# own mtime says nothing about writes happening beneath it.
newest_mtime() {
    local tree="$1"
    find "${tree}" -mount -printf '%T@\n' 2>/dev/null |
        sort -rn | head -n 1 | cut -d. -f1
}

shopt -s nullglob

for runner_dir in "${RUNNER_ROOT}"/*/; do
    runner="$(basename "${runner_dir}")"

    # A symlinked runner directory could point anywhere; refuse rather than
    # follow it. Same for the subdirectories acted on below.
    if [[ -L "${runner_dir%/}" ]]; then
        log "WARNING: skipping ${runner}, it is a symlink"
        continue
    fi

    # A directory is only a runner if it has the layout we expect. Anything
    # else under the root -- a backup, someone's scratch dir -- is left alone.
    [[ -d "${runner_dir}_work" ]] && [[ ! -L "${runner_dir}_work" ]] || continue

    now_epoch="$(date -u +%s)"

    # 1. Self-update staging payload. Present only after an upgrade, never
    #    read again, and a byte-for-byte duplicate of `externals.<version>/`.
    update_dir="${runner_dir}_work/_update"
    if [[ -d "${update_dir}" ]] && [[ ! -L "${update_dir}" ]]; then
        newest="$(newest_mtime "${update_dir}")"
        if [[ -z "${newest}" ]]; then
            log "WARNING: cannot determine age of ${runner}/_work/_update; skipping"
        elif [[ "$(((now_epoch - newest) / 60))" -gt "${update_age_minutes}" ]]; then
            log "stale self-update payload ${runner}/_work/_update (idle ~$(((now_epoch - newest) / 3600))h) -> remove"
            remove "${update_dir}"
        else
            log "keeping ${runner}/_work/_update (written to recently)"
        fi
    fi

    # 2. Runner and worker logs. These are the only record of what a job did
    #    once the Actions-side logs expire, so they get a retention window in
    #    days rather than the job-scale threshold used everywhere else.
    diag_dir="${runner_dir}_diag"
    if [[ -d "${diag_dir}" ]] && [[ ! -L "${diag_dir}" ]]; then
        while IFS= read -r -d '' logfile; do
            log "stale diag log ${logfile#"${RUNNER_ROOT}"/} -> remove"
            remove "${logfile}"
        done < <(find "${diag_dir}" -mount -type f -name '*.log' -mmin "+${diag_age_minutes}" -print0 2>/dev/null)
    fi
done

log "disk after: $(disk_usage)"
log "done"
