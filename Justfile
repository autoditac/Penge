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

# --- Docs ---------------------------------------------------------------------

docs:
    @command -v mkdocs >/dev/null || (echo "mkdocs missing; uv tool install mkdocs-material"; exit 1)
    mkdocs serve

docs-build:
    mkdocs build --strict
