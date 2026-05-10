#!/usr/bin/env bash
# scripts/snapshot.sh — encrypted DuckDB → Parquet snapshot.
#
# Exports every user table in a DuckDB database to Parquet files in a
# scratch directory, packs them into a tar archive, pipes the tar
# through `age`, and writes a single
# `<root>/duckdb/duckdb-<ts>.tar.age` artefact (plus a `.sha256`
# sidecar). The unencrypted Parquet/tar bytes never leave the scratch
# directory, which is wiped on exit.
#
# Usage:
#   ./scripts/snapshot.sh --duckdb PATH [--root DIR] [--label LABEL]
#
# Env:
#   PENGE_BACKUP_ROOT            backup root (default ./backups)
#   PENGE_BACKUP_RECIPIENTS      comma-separated age public keys
#   PENGE_BACKUP_RECIPIENTS_FILE file with one recipient per line

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib_backup.sh
source "${SCRIPT_DIR}/lib_backup.sh"

DUCKDB_PATH=""
ROOT_FLAG=""
LABEL=""

usage() {
    sed -n '2,18p' "$0"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --duckdb)
            DUCKDB_PATH="$2"
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

[[ -n "${DUCKDB_PATH}" ]] || penge::die "missing --duckdb PATH"
[[ -r "${DUCKDB_PATH}" ]] || penge::die "duckdb file not readable: ${DUCKDB_PATH}"

penge::require_cmd duckdb
penge::require_cmd age
penge::require_cmd tar
penge::require_cmd sha256sum

ROOT="$(penge::backup_root "${ROOT_FLAG}")"
TS="$(penge::timestamp)"
SLUG="${LABEL:+-${LABEL}}"
OUT="${ROOT}/duckdb/duckdb-${TS}${SLUG}.tar.age"

mapfile -t RECIPIENT_ARGS < <(penge::age_recipient_args)

# Scratch directory under the backup root, never under /tmp. Cleaned
# up on every exit path via the trap below. The same trap also drops
# any partially written ${OUT} so a failing pipeline doesn't leave a
# truncated artefact behind for operators to mistake for a real one.
SCRATCH="${ROOT}/duckdb/.scratch-${TS}"
mkdir -p "${SCRATCH}"
SUCCESS=0
cleanup() {
    rm -rf "${SCRATCH}"
    if (( SUCCESS == 0 )); then
        rm -f -- "${OUT}"
    fi
}
trap cleanup EXIT INT TERM

penge::info "snapshotting DuckDB → ${OUT}"

# Enumerate user tables across all schemas (DuckDB's information_schema
# excludes its own internal catalogues by default). Emit each row as a
# tab-separated `schema<TAB>table` pair so callers don't have to
# re-quote identifiers; we double-quote both sides for the CREATE/COPY
# statements below to handle reserved words and mixed case safely.
TABLES_FILE="${SCRATCH}/tables.tsv"
duckdb -readonly -noheader -list "${DUCKDB_PATH}" \
    "SELECT table_schema || chr(9) || table_name
       FROM information_schema.tables
      WHERE table_type = 'BASE TABLE'
      ORDER BY 1;" >"${TABLES_FILE}"

if [[ ! -s "${TABLES_FILE}" ]]; then
    penge::warn "no user tables found in ${DUCKDB_PATH}; producing an empty snapshot"
fi

MANIFEST="${SCRATCH}/manifest.tsv"
: >"${MANIFEST}"

# Quote a SQL identifier (double-quote, escaping embedded quotes) so it
# is safe to interpolate into DuckDB SELECT/COPY statements.
quote_ident() {
    local raw="$1"
    printf '"%s"' "${raw//\"/\"\"}"
}

while IFS=$'\t' read -r schema table; do
    [[ -z "${schema}" || -z "${table}" ]] && continue
    qualified="$(quote_ident "${schema}").$(quote_ident "${table}")"
    # Sanitise schema/table for the on-disk filename — strip anything
    # that isn't [A-Za-z0-9_.-] so the tar member is portable.
    safe="${schema}.${table}"
    safe="${safe//[^A-Za-z0-9_.-]/_}"
    parquet="${SCRATCH}/${safe}.parquet"
    duckdb -readonly "${DUCKDB_PATH}" \
        "COPY (SELECT * FROM ${qualified}) TO '${parquet}' (FORMAT PARQUET);"
    rows="$(duckdb -readonly -noheader -list "${DUCKDB_PATH}" \
        "SELECT count(*) FROM ${qualified};")"
    printf '%s.%s\t%s\t%s\n' "${schema}" "${table}" "${safe}.parquet" "${rows}" >>"${MANIFEST}"
done <"${TABLES_FILE}"

# Build the tar member list explicitly via NUL-delimited find output to avoid
# word-splitting glob results. Encrypt the tar stream as it is written so the
# unencrypted archive never lands on disk.
MEMBERS_FILE="${SCRATCH}/.tar-members"
(
    cd "${SCRATCH}"
    printf 'manifest.tsv\0'
    find . -maxdepth 1 -type f -name '*.parquet' -printf '%P\0'
) >"${MEMBERS_FILE}"

tar -C "${SCRATCH}" --null -T "${MEMBERS_FILE}" -cf - \
    | age "${RECIPIENT_ARGS[@]}" -o "${OUT}"

[[ -s "${OUT}" ]] || penge::die "encrypted snapshot is empty: ${OUT}"

penge::write_sha256 "${OUT}"
SUCCESS=1
penge::info "wrote $(stat -c '%s' "${OUT}") bytes → ${OUT}"
penge::info "sha256 sidecar: ${OUT}.sha256"
