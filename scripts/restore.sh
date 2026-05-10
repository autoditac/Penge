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
#   ./scripts/restore.sh --input PATH --database-url URL [--identity FILE] [--skip-hash-check]
#   ./scripts/restore.sh --input PATH --duckdb-out DIR     [--identity FILE] [--skip-hash-check]
#
# Flags:
#   --skip-hash-check   skip verification of the .sha256 sidecar (and
#                       allow restoring an artefact whose sidecar is
#                       absent). Use with care — this disables the
#                       integrity check the encrypted blob ships with.
#
# Env:
#   PENGE_BACKUP_IDENTITY_FILE  age private-key file (overridden by --identity)

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib_backup.sh
source "${SCRIPT_DIR}/lib_backup.sh"
penge::require_gnu_userland

INPUT=""
DB_URL=""
DUCKDB_OUT=""
IDENTITY="${PENGE_BACKUP_IDENTITY_FILE:-}"
SKIP_HASH=0

usage() {
    sed -n '2,24p' "$0"
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

# Refuse to feed a Postgres dump into tar (or vice versa). The
# encrypted artefact's filename suffix encodes the producer:
#   *.sql.age  → backup.sh   (replay via psql)
#   *.tar.age  → snapshot.sh (extract via tar)
# A mismatch between mode and suffix almost always means the operator
# pointed --input at the wrong file; fail fast with a clear error
# rather than streaming SQL into tar or a tar archive into psql.
if [[ -n "${DB_URL}" && "${INPUT}" != *.sql.age ]]; then
    penge::die "--database-url mode expects a *.sql.age artefact, got: ${INPUT}"
fi
if [[ -n "${DUCKDB_OUT}" && "${INPUT}" != *.tar.age ]]; then
    penge::die "--duckdb-out mode expects a *.tar.age artefact, got: ${INPUT}"
fi

penge::require_cmd age
mapfile -t IDENTITY_ARGS < <(penge::age_identity_args "${IDENTITY}")

# Verify the integrity sidecar before touching the artefact, unless the
# operator has explicitly opted out (e.g. the sidecar got lost).
if [[ ${SKIP_HASH} -eq 0 ]]; then
    penge::require_cmd sha256sum
    if [[ -r "${INPUT}.sha256" ]]; then
        penge::info "verifying ${INPUT}.sha256"
        (cd "$(dirname -- "${INPUT}")" && sha256sum -c "$(basename -- "${INPUT}").sha256") \
            || penge::die "sha256 mismatch for ${INPUT}"
    else
        penge::die "missing sidecar ${INPUT}.sha256 (pass --skip-hash-check to override)"
    fi
fi

if [[ -n "${DB_URL}" ]]; then
    penge::require_cmd psql
    LIBPQ_URL="$(penge::libpq_url "${DB_URL}")"
    # Redact any userinfo (user[:password]) before logging — the URL
    # may include a password we don't want in CI logs or scrollback.
    # Only rewrite when userinfo is actually present so URLs without
    # credentials (e.g. postgresql://localhost/db) stay readable.
    REDACTED_URL="${LIBPQ_URL}"
    if [[ "${LIBPQ_URL}" =~ ^([^:]+://)([^/@]+)@(.*)$ ]]; then
        REDACTED_URL="${BASH_REMATCH[1]}***@${BASH_REMATCH[3]}"
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
    # restore output directory so we can list and validate every
    # member BEFORE extracting. The recipient public key is not
    # secret, so an attacker who knows it could craft and encrypt a
    # malicious tarball for it; this pre-flight rejects:
    #   * absolute paths and `..` traversal
    #   * symlinks and hardlinks (any link could escape the root)
    #   * device, FIFO, or other non-regular member types
    SCRATCH_TAR="${DUCKDB_OUT}/.restore.$$.tar"
    trap 'rm -f -- "${SCRATCH_TAR}"' EXIT
    age -d "${IDENTITY_ARGS[@]}" "${INPUT}" >"${SCRATCH_TAR}"

    # `tar -tvf` prints a `ls -l`-style listing whose first character
    # encodes the entry type: '-' regular, 'd' dir, 'l' symlink, 'h'
    # hardlink, 'b'/'c' devices, 's' socket, 'p' fifo. Only '-' and
    # 'd' are safe.
    while IFS= read -r line; do
        [[ -z "${line}" ]] && continue
        type_char="${line:0:1}"
        case "${type_char}" in
            -|d) ;;
            *) penge::die "refusing tar member with unsafe type '${type_char}': ${line}" ;;
        esac
    done < <(tar -tvf "${SCRATCH_TAR}")

    while IFS= read -r member; do
        # Reject genuine traversal (a path component that *equals* `..`)
        # and absolute paths / embedded newlines, but allow `..` to
        # appear inside a single component — snapshot.sh's `safe`
        # sanitiser preserves dots in schema/table names, so legitimate
        # members like `main.foo..bar.parquet` must still extract.
        if [[ "${member}" == /* ]] \
            || [[ "${member}" == *$'\n'* ]] \
            || [[ "${member}" == ".." ]] \
            || [[ "${member}" == "../"* ]] \
            || [[ "${member}" == */".."/* ]] \
            || [[ "${member}" == */".." ]]; then
            penge::die "refusing tar member with unsafe path: ${member}"
        fi
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
