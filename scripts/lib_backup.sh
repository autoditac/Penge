#!/usr/bin/env bash
# Shared helpers for the Penge backup / snapshot / restore tooling.
#
# Sourced (not executed) by the sibling shell scripts in this directory.
# All functions are pure-bash; the only external commands we rely on are
# coreutils, `age`, `pg_dump`/`psql`, and `duckdb`.
#
# Hard rule: nothing in here writes to /tmp. Caller scripts create a
# scratch directory under the configured backup root and clean it up.

set -euo pipefail

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

penge::log() {
    # Structured-ish log line on stderr so stdout stays clean for pipes.
    local level="$1"
    shift
    printf '[%s] [%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${level}" "$*" >&2
}

penge::info() { penge::log INFO "$*"; }
penge::warn() { penge::log WARN "$*"; }
penge::die() {
    penge::log ERROR "$1"
    exit "${2:-1}"
}

# ---------------------------------------------------------------------------
# Tooling probes
# ---------------------------------------------------------------------------

penge::require_cmd() {
    local cmd="$1"
    command -v "${cmd}" >/dev/null 2>&1 \
        || penge::die "required command not found in PATH: ${cmd}"
}

# Preflight: the scripts in this directory rely on GNU userland for
# `date -d` / ISO-week formatting (`%G`/`%V`), `find -printf`, GNU tar's
# `--null -T`, and `stat -c`. macOS / BSD ships POSIX/BSD variants that
# silently differ. Probe the few that matter and die with a clear
# pointer to the runbook so an operator on macOS knows to install
# Homebrew coreutils/findutils/gnu-tar and put the gnubin dirs on PATH.
penge::require_gnu_userland() {
    if ! date -u -d '2020-01-01T00:00:00Z' +%G-W%V >/dev/null 2>&1; then
        penge::die "GNU date is required (date -d / %G%V). On macOS: \
brew install coreutils findutils gnu-tar and prepend the gnubin dirs \
to PATH. See docs/runbook/backup-restore.md."
    fi
    if ! find /tmp -maxdepth 0 -printf '' >/dev/null 2>&1; then
        penge::die "GNU find is required (find -printf). See docs/runbook/backup-restore.md."
    fi
}

# Print the size of a regular file in bytes. GNU coreutils uses
# `stat -c %s`, BSD/macOS `stat -f %z`; try both so log lines and
# tests work on either.
penge::file_size() {
    local f="$1"
    stat -c '%s' "${f}" 2>/dev/null || stat -f '%z' "${f}"
}

# ---------------------------------------------------------------------------
# Timestamps and paths
# ---------------------------------------------------------------------------

# UTC ISO-8601 basic-format timestamp, safe in filenames and lexically
# sortable: 20260508T134507Z.
penge::timestamp() {
    date -u +%Y%m%dT%H%M%SZ
}

# Resolve the backup root, creating subdirs on demand. Defaults to
# ./backups under the repo when neither flag nor env var is set; the
# directory is gitignored.
penge::backup_root() {
    local root="${1:-${PENGE_BACKUP_ROOT:-./backups}}"
    mkdir -p "${root}/postgres" "${root}/duckdb"
    printf '%s\n' "${root}"
}

# ---------------------------------------------------------------------------
# Recipients (age public keys)
# ---------------------------------------------------------------------------

# Build the `-r <recipient>` arg list for `age` from
# PENGE_BACKUP_RECIPIENTS (comma- or whitespace-separated public keys)
# and/or PENGE_BACKUP_RECIPIENTS_FILE (path to a file with one recipient
# per line, blank lines and `#`-comments ignored).
#
# Writes the args, one per line, to stdout.
penge::age_recipient_args() {
    local raw="${PENGE_BACKUP_RECIPIENTS:-}"
    local file="${PENGE_BACKUP_RECIPIENTS_FILE:-}"
    local count=0

    if [[ -n "${raw}" ]]; then
        # Replace commas with spaces, then iterate.
        local key
        for key in ${raw//,/ }; do
            [[ -z "${key}" ]] && continue
            printf -- '-r\n%s\n' "${key}"
            count=$((count + 1))
        done
    fi

    if [[ -n "${file}" ]]; then
        [[ -r "${file}" ]] || penge::die "recipients file not readable: ${file}"
        printf -- '-R\n%s\n' "${file}"
        # We can't cheaply count lines without reading; trust the file
        # has at least one entry and let `age` complain otherwise.
        count=$((count + 1))
    fi

    if [[ ${count} -eq 0 ]]; then
        penge::die "no age recipients configured (set PENGE_BACKUP_RECIPIENTS or PENGE_BACKUP_RECIPIENTS_FILE)"
    fi
}

# ---------------------------------------------------------------------------
# Identity (age private key) for restore
# ---------------------------------------------------------------------------

penge::age_identity_args() {
    local file="${1:-${PENGE_BACKUP_IDENTITY_FILE:-}}"
    [[ -n "${file}" ]] || penge::die "no age identity configured (set PENGE_BACKUP_IDENTITY_FILE or pass --identity)"
    [[ -r "${file}" ]] || penge::die "age identity file not readable: ${file}"
    printf -- '-i\n%s\n' "${file}"
}

# ---------------------------------------------------------------------------
# DATABASE_URL normalisation
# ---------------------------------------------------------------------------

# SQLAlchemy uses `postgresql+psycopg://...` while libpq tools expect
# `postgresql://...`. Strip the driver suffix non-destructively. We
# match the literal prefix and rebuild rather than using a
# substitution pattern so the slashes are unambiguous.
penge::libpq_url() {
    local url="${1:?database URL required}"
    if [[ "${url}" == postgresql+psycopg://* ]]; then
        printf '%s\n' "postgresql://${url#postgresql+psycopg://}"
    else
        printf '%s\n' "${url}"
    fi
}

# ---------------------------------------------------------------------------
# Integrity sidecar
# ---------------------------------------------------------------------------

# Write `<file>.sha256` next to the artefact so an operator can verify
# the encrypted blob hasn't bit-rotted before attempting a restore.
# The sidecar records only the basename (we cd into the artefact's
# directory before invoking sha256sum) so the artefact + sidecar pair
# can be moved to another host / path and `sha256sum -c` still works.
penge::write_sha256() {
    local target="$1"
    local dir base
    dir="$(dirname -- "${target}")"
    base="$(basename -- "${target}")"
    (cd "${dir}" && sha256sum "${base}" >"${base}.sha256")
}
