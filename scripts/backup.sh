#!/usr/bin/env bash
# scripts/backup.sh — encrypted Postgres logical backup.
#
# Pipes `pg_dump` (plain SQL) through `age` to one or more recipient
# public keys and writes a timestamped `<root>/postgres/pg-<ts>.sql.age`
# artefact, accompanied by a `.sha256` sidecar.
#
# The script never holds an unencrypted dump on disk: pg_dump streams
# straight into age via a pipe.
#
# Usage:
#   ./scripts/backup.sh [--database-url URL] [--root DIR] [--label LABEL]
#
# Env:
#   DATABASE_URL                 libpq or SQLAlchemy URL (required if no flag)
#   PENGE_BACKUP_ROOT            backup root (default ./backups)
#   PENGE_BACKUP_RECIPIENTS      comma-separated age public keys
#   PENGE_BACKUP_RECIPIENTS_FILE file with one recipient per line
#
# Exit codes:
#   0  success
#   1  configuration / dependency error
#   2  pg_dump failure (encrypted artefact is removed before exit)
#   3  age encryption failure (encrypted artefact is removed before exit)

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib_backup.sh
source "${SCRIPT_DIR}/lib_backup.sh"

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

DB_URL="${DATABASE_URL:-}"
ROOT_FLAG=""
LABEL=""

usage() {
    sed -n '2,22p' "$0"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --database-url)
            DB_URL="$2"
            shift 2
            ;;
        --root)
            ROOT_FLAG="$2"
            shift 2
            ;;
        --label)
            LABEL="$2"
            shift 2
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

[[ -n "${DB_URL}" ]] || penge::die "no database URL (set DATABASE_URL or pass --database-url)"

# ---------------------------------------------------------------------------
# Tool probes
# ---------------------------------------------------------------------------

penge::require_cmd pg_dump
penge::require_cmd age
penge::require_cmd sha256sum

# ---------------------------------------------------------------------------
# Resolve paths and recipients up-front so we fail fast.
# ---------------------------------------------------------------------------

ROOT="$(penge::backup_root "${ROOT_FLAG}")"
TS="$(penge::timestamp)"
SLUG="${LABEL:+-${LABEL}}"
OUT="${ROOT}/postgres/pg-${TS}${SLUG}.sql.age"

mapfile -t RECIPIENT_ARGS < <(penge::age_recipient_args)

LIBPQ_URL="$(penge::libpq_url "${DB_URL}")"

# ---------------------------------------------------------------------------
# pg_dump | age
# ---------------------------------------------------------------------------
#
# We want to fail loudly if pg_dump errors out, even when its output is
# piped into age. `set -o pipefail` is already on (see lib_backup.sh)
# so a non-zero pg_dump exit propagates through the pipeline.

penge::info "backing up Postgres → ${OUT}"

# Plain SQL dump (default format) — restorable with `psql -f -`. We
# include `--no-owner --no-privileges` so a restore into a fresh role
# stays portable; ADR-0025 documents the trade-off.
#
# Inspect PIPESTATUS so we can map pg_dump and age failures to the
# documented exit codes (2 = pg_dump, 3 = age). Disable both errexit
# and pipefail around the pipeline so neither component's non-zero
# exit aborts the script before we capture statuses and clean up.
set +e
set +o pipefail
pg_dump \
    --dbname="${LIBPQ_URL}" \
    --format=plain \
    --no-owner \
    --no-privileges \
    --quote-all-identifiers \
    | age "${RECIPIENT_ARGS[@]}" -o "${OUT}"
PIPE_STATUS=("${PIPESTATUS[@]}")
set -e
set -o pipefail

if (( PIPE_STATUS[0] != 0 )); then
    rm -f -- "${OUT}"
    penge::die "pg_dump failed (exit ${PIPE_STATUS[0]}); artefact removed" 2
fi
if (( PIPE_STATUS[1] != 0 )); then
    rm -f -- "${OUT}"
    penge::die "age encryption failed (exit ${PIPE_STATUS[1]}); artefact removed" 3
fi

# Verify the artefact looks plausible before declaring success.
[[ -s "${OUT}" ]] || penge::die "encrypted artefact is empty: ${OUT}"

penge::write_sha256 "${OUT}"
penge::info "wrote $(stat -c '%s' "${OUT}") bytes → ${OUT}"
penge::info "sha256 sidecar: ${OUT}.sha256"
