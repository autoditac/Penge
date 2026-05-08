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
