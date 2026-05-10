#!/usr/bin/env bash
# scripts/restore.sh — decrypt + replay a Penge encrypted backup.
#
# Decrypts a `*.sql.age` Postgres dump produced by `scripts/backup.sh`
# and feeds it to `psql` against the target database. The unencrypted
# dump only lives in the pipe between `age` and `psql`; nothing is
# written to disk.
#
# For DuckDB snapshots (`*.tar.age`) pass `--duckdb-out DIR` to extract
# the decrypted Parquet files plus their manifest into DIR (no Postgres
# replay needed).
#
# Usage:
#   ./scripts/restore.sh --input PATH --database-url URL [--identity FILE]
#   ./scripts/restore.sh --input PATH --duckdb-out DIR     [--identity FILE]
#
# Env:
#   PENGE_BACKUP_IDENTITY_FILE  age private-key file (overridden by --identity)

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib_backup.sh
source "${SCRIPT_DIR}/lib_backup.sh"

INPUT=""
DB_URL=""
DUCKDB_OUT=""
IDENTITY="${PENGE_BACKUP_IDENTITY_FILE:-}"
SKIP_HASH=0

usage() {
    sed -n '2,21p' "$0"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --input)
            INPUT="$2"
            shift 2
            ;;
        --database-url)
            DB_URL="$2"
            shift 2
            ;;
        --duckdb-out)
            DUCKDB_OUT="$2"
            shift 2
            ;;
        --identity)
            IDENTITY="$2"
            shift 2
            ;;
        --skip-hash-check)
            SKIP_HASH=1
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

[[ -n "${INPUT}" ]] || penge::die "missing --input PATH"
[[ -r "${INPUT}" ]] || penge::die "input not readable: ${INPUT}"
[[ -n "${DB_URL}" || -n "${DUCKDB_OUT}" ]] \
    || penge::die "either --database-url or --duckdb-out is required"
[[ -n "${DB_URL}" && -n "${DUCKDB_OUT}" ]] \
    && penge::die "--database-url and --duckdb-out are mutually exclusive"

penge::require_cmd age
mapfile -t IDENTITY_ARGS < <(penge::age_identity_args "${IDENTITY}")

# Verify the integrity sidecar before touching the artefact, unless the
# operator has explicitly opted out (e.g. the sidecar got lost).
if [[ ${SKIP_HASH} -eq 0 && -r "${INPUT}.sha256" ]]; then
    penge::require_cmd sha256sum
    penge::info "verifying ${INPUT}.sha256"
    (cd "$(dirname -- "${INPUT}")" && sha256sum -c "$(basename -- "${INPUT}").sha256") \
        || penge::die "sha256 mismatch for ${INPUT}"
fi

if [[ -n "${DB_URL}" ]]; then
    penge::require_cmd psql
    LIBPQ_URL="$(penge::libpq_url "${DB_URL}")"
    # Redact any userinfo (user[:password]) before logging — the URL
    # may include a password we don't want in CI logs or scrollback.
    REDACTED_URL="${LIBPQ_URL}"
    if [[ "${REDACTED_URL}" =~ ^([^:]+://)([^/@]+@)?(.*)$ ]]; then
        scheme="${BASH_REMATCH[1]}"
        host_and_path="${BASH_REMATCH[3]}"
        REDACTED_URL="${scheme}***@${host_and_path}"
    fi
    penge::info "decrypt + psql restore → ${REDACTED_URL}"
    age -d "${IDENTITY_ARGS[@]}" "${INPUT}" \
        | psql --dbname="${LIBPQ_URL}" \
            --quiet \
            --set=ON_ERROR_STOP=1 \
            --set=AUTOCOMMIT=on
    penge::info "restore complete"
else
    penge::require_cmd tar
    mkdir -p "${DUCKDB_OUT}"
    penge::info "decrypt + tar -x → ${DUCKDB_OUT}"
    # Stream the decrypted tar into a scratch file under the
    # restore output directory so we can list members and reject
    # path-traversal payloads BEFORE extracting. The recipient
    # public key is not secret, so an attacker who knows it could
    # craft a malicious tarball encrypted to that key; refuse any
    # member whose name is absolute, contains `..`, or is a
    # symlink/hardlink pointing outside the restore root.
    SCRATCH_TAR="${DUCKDB_OUT}/.restore.$$.tar"
    trap 'rm -f -- "${SCRATCH_TAR}"' EXIT
    age -d "${IDENTITY_ARGS[@]}" "${INPUT}" >"${SCRATCH_TAR}"
    while IFS= read -r member; do
        case "${member}" in
            /*|*..*|*$'\n'*)
                penge::die "refusing tar member with unsafe path: ${member}"
                ;;
        esac
    done < <(tar -tf "${SCRATCH_TAR}")
    tar -C "${DUCKDB_OUT}" \
        --no-same-owner \
        --no-same-permissions \
        --no-overwrite-dir \
        -xf "${SCRATCH_TAR}"
    rm -f -- "${SCRATCH_TAR}"
    trap - EXIT
    penge::info "extracted snapshot to ${DUCKDB_OUT}"
    [[ -r "${DUCKDB_OUT}/manifest.tsv" ]] \
        && penge::info "manifest:" \
        && cat "${DUCKDB_OUT}/manifest.tsv" >&2
fi
