#!/usr/bin/env bash
# scripts/prune.sh — retention pruning for encrypted backup artefacts.
#
# Buckets every `*.age` artefact under the given root by ISO date /
# week / month derived from the filename timestamp (UTC), keeps the
# `--daily` newest dailies, the `--weekly` newest distinct ISO weeks,
# and the `--monthly` newest distinct calendar months. Anything that
# falls into none of those buckets is removed (along with its
# `.sha256` sidecar).
#
# Filenames must contain a `YYYYMMDDTHHMMSSZ` substring as produced by
# `scripts/backup.sh` / `scripts/snapshot.sh` (and the `lib_backup.sh::timestamp`
# helper). Anything else is left untouched.
#
# Usage:
#   ./scripts/prune.sh [--root DIR] [--daily 14] [--weekly 8] [--monthly 12] [--dry-run]
#
# Defaults follow the configurable retention policy documented in
# ADR-0025: 14 daily, 8 weekly, 12 monthly artefacts per category.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib_backup.sh
source "${SCRIPT_DIR}/lib_backup.sh"

ROOT_FLAG=""
DAILY="${PENGE_BACKUP_RETENTION_DAILY:-14}"
WEEKLY="${PENGE_BACKUP_RETENTION_WEEKLY:-8}"
MONTHLY="${PENGE_BACKUP_RETENTION_MONTHLY:-12}"
DRY_RUN=0

usage() {
    sed -n '2,20p' "$0"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --root)
            ROOT_FLAG="$2"
            shift 2
            ;;
        --daily)
            DAILY="$2"
            shift 2
            ;;
        --weekly)
            WEEKLY="$2"
            shift 2
            ;;
        --monthly)
            MONTHLY="$2"
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
            penge::die "unknown argument: $1"
            ;;
    esac
done

ROOT="$(penge::backup_root "${ROOT_FLAG}")"

# Collect all `*.age` artefacts (ignore sidecars). For every file we
# emit a TSV row: <ts>\t<iso_date>\t<iso_week>\t<iso_month>\t<path>
# sorted descending by timestamp so the head of each bucket is the
# newest.

penge::info "pruning ${ROOT} (daily=${DAILY} weekly=${WEEKLY} monthly=${MONTHLY})"

# Gather candidates without invoking `find` more than once.
mapfile -t CANDIDATES < <(find "${ROOT}" -type f -name '*.age' 2>/dev/null | sort)

if [[ ${#CANDIDATES[@]} -eq 0 ]]; then
    penge::info "no artefacts to prune"
    exit 0
fi

# AWK extracts the timestamp, computes day / ISO-week / month buckets,
# and prints `path<TAB>day<TAB>week<TAB>month` rows sorted newest-first.
# We use GNU date for ISO-week math because POSIX awk doesn't expose it.
declare -A KEEP=()

for path in "${CANDIDATES[@]}"; do
    base="$(basename -- "${path}")"
    # Match the YYYYMMDDTHHMMSSZ pattern.
    if [[ ! "${base}" =~ ([0-9]{8}T[0-9]{6}Z) ]]; then
        penge::warn "skipping (no timestamp in name): ${path}"
        continue
    fi
    ts="${BASH_REMATCH[1]}"
    # Re-shape into something `date -d` can parse: 20260508T134507Z
    # → 2026-05-08T13:45:07Z.
    iso="${ts:0:4}-${ts:4:2}-${ts:6:2}T${ts:9:2}:${ts:11:2}:${ts:13:2}Z"
    day="$(date -u -d "${iso}" +%Y-%m-%d)"
    week="$(date -u -d "${iso}" +%G-W%V)"
    month="$(date -u -d "${iso}" +%Y-%m)"
    printf '%s\t%s\t%s\t%s\t%s\n' "${ts}" "${day}" "${week}" "${month}" "${path}"
done | sort -r >"${ROOT}/.prune-index"

# Pick the newest artefact for each distinct day / week / month bucket
# until the per-category quota is reached.
pick_bucket() {
    local col="$1" quota="$2"
    awk -v col="${col}" -v quota="${quota}" '
        BEGIN { kept = 0 }
        {
            key = $col
            if (!(key in seen)) {
                seen[key] = 1
                if (kept < quota) {
                    kept++
                    print $5
                }
            }
        }
    ' "${ROOT}/.prune-index"
}

while IFS= read -r p; do KEEP["${p}"]=daily; done < <(pick_bucket 2 "${DAILY}")
while IFS= read -r p; do KEEP["${p}"]=${KEEP[$p]:-weekly}; done < <(pick_bucket 3 "${WEEKLY}")
while IFS= read -r p; do KEEP["${p}"]=${KEEP[$p]:-monthly}; done < <(pick_bucket 4 "${MONTHLY}")

REMOVED=0
KEPT=0
while IFS= read -r line; do
    path="${line##*$'\t'}"
    if [[ -n "${KEEP[$path]+x}" ]]; then
        KEPT=$((KEPT + 1))
        continue
    fi
    REMOVED=$((REMOVED + 1))
    if [[ ${DRY_RUN} -eq 1 ]]; then
        penge::info "would remove: ${path}"
    else
        penge::info "removing: ${path}"
        rm -f -- "${path}" "${path}.sha256"
    fi
done <"${ROOT}/.prune-index"

rm -f "${ROOT}/.prune-index"
penge::info "kept ${KEPT}, removed ${REMOVED}"
