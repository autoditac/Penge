# Container images

Application images are built from `apps/<name>/Containerfile`.
The first image is the modern WebUI:

```text
apps/web/Containerfile
```

CI builds application images on pull requests without pushing them.
Published releases push images to GHCR and attach supply-chain metadata.

## Image names

Release images use this naming convention:

```text
ghcr.io/autoditac/penge/<app>
```

For the WebUI:

```text
ghcr.io/autoditac/penge/web
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

## Release publishing

The release workflow pushes application images on:

- `release: published`
- `workflow_dispatch`

Each pushed image gets:

- an image tag;
- a commit-SHA tag;
- a Buildx SBOM request;
- a GitHub build-provenance attestation for the pushed digest.

After a release, copy the immutable image digest into the deployment compose
file before updating the home server.
