# Container images

Application images are built from `apps/<name>/Containerfile`:

```text
apps/web/Containerfile   # WebUI (nginx serving the Vite build)
apps/api/Containerfile   # FastAPI read API (uv-built virtualenv)
```

CI builds application images on pull requests without pushing them.
Every merge to `main` publishes fresh `:main` and `:<commit-sha>` images to
GHCR (see [ADR-0044](../decisions/0044-continuous-image-publishing-and-nas-auto-deploy.md)).
Published releases additionally push `<release-tag>` images to GHCR and
attach supply-chain metadata.

## Image names

Release images use this naming convention:

```text
ghcr.io/autoditac/penge/<app>
```

For the WebUI and the read API:

```text
ghcr.io/autoditac/penge/web
ghcr.io/autoditac/penge/api
```

Release builds tag each image with the release tag and commit SHA.
Manual release workflow dispatches use a `manual-<run-number>` tag plus the
commit SHA.

## Local build

Build the WebUI image locally:

```bash
just web-ui-image
```

Run it locally:

```bash
docker run --rm -p 127.0.0.1:8080:8080 penge/web:dev
```

Then open <http://127.0.0.1:8080>.

Build the read-API image locally:

```bash
just api-image
```

Run it locally (the container binds `0.0.0.0:8000` internally; publish it
on loopback only). On Linux, `host.docker.internal` needs the explicit
`--add-host` mapping shown below (Docker Desktop provides it by default):

```bash
docker run --rm -p 127.0.0.1:8000:8000 \
  --add-host=host.docker.internal:host-gateway \
  -e DATABASE_URL=postgresql+psycopg://penge:penge@host.docker.internal:5432/penge \
  penge/api:dev
```

Then check <http://127.0.0.1:8000/meta/freshness>.

The image runs as a non-root user. Staged import uploads live under
`PENGE_IMPORT_DIR=/data/imports`; mount a volume at `/data` to keep staged
sessions across container restarts. All other knobs (`PENGE_API_CORS_ORIGINS`,
`PENGE_MCP_SUGGEST_COMMAND`, ...) are plain environment variables, see
[the API docs](../api/index.md).

## Build-context safety

The root `.dockerignore` excludes local finance data and build artefacts,
including:

- `data/`
- `reports/`
- `backups/`
- `secrets/`
- `.env*`
- `*.csv`, `*.pdf`, `*.parquet`, and DuckDB files
- `node_modules/`, `dist/`, caches, and coverage output

Do not pass ad-hoc alternate build contexts that bypass this file.
Never copy real statements, reports, backups, or local databases into image
fixtures.

## Merge and release publishing

On every merge to `main`, the `publish-images` job in `.github/workflows/ci.yml`
pushes:

- `ghcr.io/autoditac/penge/<app>:main` (moving tag — always the latest
  `main` build);
- `ghcr.io/autoditac/penge/<app>:<commit-sha>` (immutable, used for pinning
  and rollback).

The release workflow additionally pushes application images on:

- `release: published`
- `workflow_dispatch`

Each pushed image gets:

- an image tag;
- a commit-SHA tag;
- a Buildx SBOM request;
- a GitHub build-provenance attestation for the pushed digest.

After a release, copy the immutable image digest into the deployment compose
file before updating the home server.
