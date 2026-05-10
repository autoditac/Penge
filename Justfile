# Penge — task runner
# Run `just` (no args) to see available recipes.

set shell := ["bash", "-eu", "-o", "pipefail", "-c"]
set dotenv-load := true

default:
    @just --list

# --- Bootstrap ----------------------------------------------------------------

# Install local toolchain (uv, pnpm, pre-commit) and project dependencies.
bootstrap:
    @echo "→ Checking required tools"
    @command -v uv >/dev/null || (echo "uv missing; install from https://docs.astral.sh/uv/"; exit 1)
    @command -v pnpm >/dev/null || (echo "pnpm missing; install via: corepack enable && corepack prepare pnpm@latest --activate"; exit 1)
    @command -v pre-commit >/dev/null || (echo "pre-commit missing; install via: uv tool install pre-commit"; exit 1)
    @command -v docker >/dev/null || (echo "docker missing"; exit 1)
    pre-commit install --install-hooks
    pre-commit install --hook-type commit-msg
    @echo "✓ bootstrap complete"

# --- Compose / dev infra ------------------------------------------------------

# Start local Postgres + Adminer.
up:
    docker compose up -d

# Stop local infra.
down:
    docker compose down

# Tail logs.
logs:
    docker compose logs -f

# --- Quality gates ------------------------------------------------------------

lint:
    pre-commit run --all-files

test:
    @echo "no tests yet — see Phase 1+ backlog"

# --- Migrations ---------------------------------------------------------------

# Apply all migrations against the local Postgres (compose must be up).
migrate-up:
    uv run --group db alembic upgrade head

# Roll all migrations back. Round-trips the schema; CI runs this on
# every PR (see .github/workflows/ci.yml :: alembic-roundtrip).
migrate-down:
    uv run --group db alembic downgrade base

# upgrade head -> downgrade base -> upgrade head: the gate the
# migrations.instructions.md hard rule #1 demands.
migrate-roundtrip:
    uv run --group db alembic upgrade head
    uv run --group db alembic downgrade base
    uv run --group db alembic upgrade head

# Create a new migration. Usage: just migrate-new "add foo column"
migrate-new MSG:
    uv run --group db alembic revision -m "{{MSG}}" --autogenerate

# --- Docs ---------------------------------------------------------------------

docs:
    @command -v mkdocs >/dev/null || (echo "mkdocs missing; uv tool install mkdocs-material"; exit 1)
    mkdocs serve

docs-build:
    mkdocs build --strict

# --- Manual entry ------------------------------------------------------------

# Record a cash-account balance. All flags forwarded to penge-manual add-balance.
# Example:
#   just manual-add-balance --entity Rouven --account "DKB Tagesgeld" \
#       --currency EUR --balance 12345.67
manual-add-balance *FLAGS:
    uv run --group db --group manual penge-manual add-balance {{FLAGS}}

# Record a real-estate valuation. Flags forwarded to penge-manual mark-property.
# Example:
#   just manual-mark-property --entity Rouven --account "Nederbyvej 36" \
#       --property "Nederbyvej 36 (DK)" --currency DKK --valuation 4500000
manual-mark-property *FLAGS:
    uv run --group db --group manual penge-manual mark-property {{FLAGS}}

# --- GLS Bank (Enable Banking PSD2) ------------------------------------------

# Forward all flags to the penge-gls CLI. Subcommands: link, authorize, sync.
# Example:
#   just ingest-gls link --redirect-url http://localhost:8765/callback
#   just ingest-gls authorize --code <CODE>
#   just ingest-gls sync --entity-name "Your Name" --days 365
ingest-gls *FLAGS:
    uv run --group db --group http --group enablebanking penge-gls {{FLAGS}}

# --- Evangelische Bank (Enable Banking PSD2) -------------------------------
#
# Forward all flags to the penge-ebank CLI. Subcommands: link, authorize, sync.
# Examples:
#   just ingest-ebank link --redirect-url http://localhost:8765/callback
#   just ingest-ebank authorize --code <CODE>
#   just ingest-ebank sync --entity-name "Your Name" --days 365
ingest-ebank *FLAGS:
    uv run --group db --group http --group enablebanking penge-ebank {{FLAGS}}

# --- Lunar (Enable Banking PSD2) -------------------------------------------
#
# Forward all flags to the penge-lunar CLI. Subcommands: link, authorize, sync.
# Examples:
#   just ingest-lunar link --redirect-url http://localhost:8765/callback
#   just ingest-lunar authorize --code <CODE>
#   just ingest-lunar sync --entity-name "Your Name" --days 365
# Aktiesparekonto subaccounts are auto-tagged with
# account.dk_tax_treatment = 'aktiesparekonto'.
ingest-lunar *FLAGS:
    uv run --group db --group http --group enablebanking penge-lunar {{FLAGS}}

# --- Growney / Sutor Bank Depotauszug --------------------------------------
#
# Forward all flags to the penge-growney CLI. Sutor Bank is the
# regulated custodian behind the Growney robo-advisor and emits
# the data as quarterly Depotauszug PDFs (no CSV export). Examples:
#   just ingest-growney --entity-name "Your Name" path/to/q1.pdf path/to/q2.pdf
ingest-growney *FLAGS:
    uv run --group db --group http --group parsers penge-growney {{FLAGS}}

# --- PFA pension Pensionsoversigt -----------------------------------------
#
# Forward all flags to the penge-pfa CLI. PFA mails an annual
# Pensionsoversigt PDF; the connector parses it via pdfplumber
# and falls back to Tesseract OCR (lang=dan+deu) for scanned
# image-only PDFs. Pass --no-ocr to disable the OCR fallback.
# Examples:
#   just ingest-pfa --entity-name "Your Name" path/to/pensionsoversigt-2025.pdf
ingest-pfa *FLAGS:
    uv run --group db --group http --group parsers --group ocr penge-pfa {{FLAGS}}

# --- Skat ABIS list (Aktiebaserede Investeringsselskaber) -----------------
#
# Forward all flags to the penge-abis CLI. Subcommands:
#   ingest <csv>                            — parse + reconcile a Skat CSV
#   override --isin X --treatment <T>       — sticky manual decision
#   override --isin X --clear               — drop a manual decision
# Examples:
#   just ingest-abis ingest data/abis-listen-2020-2025.csv
#   just ingest-abis override --isin DE0002635281 --treatment lagerbeskatning
ingest-abis *FLAGS:
    uv run --group db penge-abis {{FLAGS}}

# --- Vault inbox watcher --------------------------------------------------
#
# The vault watcher tails an inbox directory and files every PDF dropped
# into it under a year/type tree (see ADR-0024). The OCR pipeline writes
# a `.txt` sidecar next to every filed document.
# Examples:
#   just vault-watch ~/Nextcloud/Finance/inbox ~/Nextcloud/Finance/vault
#   just vault-once  ~/Nextcloud/Finance/inbox ~/Nextcloud/Finance/vault
#   just vault-fixtures   # regenerate synthetic test PDFs
vault-watch *FLAGS:
    uv run --group vault --group parsers --group ocr penge-vault watch {{FLAGS}}

vault-once INBOX VAULT:
    uv run --group vault --group parsers --group ocr penge-vault watch {{INBOX}} {{VAULT}} --once

vault-fixtures:
    uv run --group parsers python tools/generate_vault_fixtures.py

# --- MCP server (TypeScript) -------------------------------------------------
#
# Skeleton MCP server (apps/mcp). See ADR-0023.
# `mcp-dev` runs the server over stdio with hot reload — point your MCP host
# (Claude Desktop, VS Code Copilot Chat) at the command shown in
# apps/mcp/README.md.

# Install TS workspace dependencies (idempotent).
mcp-install:
    pnpm --filter @penge/mcp install

# Run the MCP server locally with hot reload.
mcp-dev:
    pnpm --filter @penge/mcp dev

# Run MCP server unit tests (vitest).
mcp-test:
    pnpm --filter @penge/mcp test

# Lint + format-check the MCP TS package.
mcp-lint:
    pnpm --filter @penge/mcp lint

# Production build (TypeScript → dist/).
mcp-build:
    pnpm --filter @penge/mcp build

# --- Encrypted backups (see ADR-0025) ----------------------------------------
#
# All four recipes are thin wrappers around the shell scripts under
# scripts/. Configure recipients via PENGE_BACKUP_RECIPIENTS (a
# comma-separated list of `age` public keys) and the identity file via
# PENGE_BACKUP_IDENTITY_FILE. See docs/runbook/backups.md.

# Take an encrypted Postgres logical backup (pg_dump | age).
# Extra flags forward to scripts/backup.sh, e.g.
#   just backup --label pre-upgrade
backup *FLAGS:
    ./scripts/backup.sh {{FLAGS}}

# Snapshot a DuckDB database to encrypted Parquet (per-table COPY | tar | age).
# Usage:
#   just snapshot ./data/penge.duckdb
#   just snapshot ./data/penge.duckdb --label pre-upgrade
snapshot DUCKDB *FLAGS:
    ./scripts/snapshot.sh --duckdb {{DUCKDB}} {{FLAGS}}

# Round-trip restore drill: decrypt the newest pg-*.sql.age and replay it
# into PENGE_TEST_DATABASE_URL (never production).
restore-test:
    @test -n "${PENGE_TEST_DATABASE_URL:-}" || (echo "PENGE_TEST_DATABASE_URL must be set" && exit 1)
    @test -n "${PENGE_BACKUP_IDENTITY_FILE:-}" || (echo "PENGE_BACKUP_IDENTITY_FILE must be set" && exit 1)
    LATEST="$(ls -1 "${PENGE_BACKUP_ROOT:-./backups}"/postgres/pg-*.sql.age | tail -n1)" && \
        ./scripts/restore.sh --input "$LATEST" --database-url "$PENGE_TEST_DATABASE_URL"

# Apply backup retention (defaults: 14 daily / 8 weekly / 12 monthly).
backup-prune *FLAGS:
    ./scripts/prune.sh {{FLAGS}}
