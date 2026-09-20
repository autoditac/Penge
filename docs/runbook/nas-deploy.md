# NAS deploy and rollback

How the `penge-api` and `penge-web` containers on the NAS
(`penge.eigmueller.de`) stay current with `main`, and how to roll them back.
See [ADR-0044](../decisions/0044-continuous-image-publishing-and-nas-auto-deploy.md)
for the design rationale.

## How it works

Every merge to `main` publishes `ghcr.io/autoditac/penge/{api,web}:main` and
`ghcr.io/autoditac/penge/{api,web}:<commit-sha>` (see the
[container images runbook](container-images.md)).

The NAS quadlets at `/etc/containers/systemd/penge-{api,web}.container`
(tracked in this repo under `deploy/nas/`) reference the moving `:main` tags
and carry `AutoUpdate=registry`.
The host nginx configuration, tracked at
`deploy/nas/penge.eigmueller.de.conf`, keeps TLS and OAuth on the host,
proxies API routes to the API container on `127.0.0.1:8001`, and proxies the
SPA to the WebUI container on `127.0.0.1:8082`.

`podman-auto-update.timer` (already enabled on the NAS, runs daily) resolves
`:main` to its current digest on each poll.
If the digest changed, it pulls the new image, restarts the container, and
watches the `HealthCmd` result.
An unhealthy new container is rolled back automatically to the previous
image; a healthy one stays.
(`Notify=healthy` in the quadlet makes systemd — and therefore
`podman-auto-update`'s success/rollback decision — wait for the first
`HealthCmd` result before treating a restart as started; without it,
Quadlet's default readiness signal fires as soon as the container process
starts, before health is known.)

Every (re)start, including auto-update-triggered ones, appends a
timestamped record of the digest that ended up running to the unit's
journal (`ExecStartPost` in the quadlet) — see "Finding the running
digest" below. This is the deploy log required for reproducibility: which
digest ran, and since when.

The GHCR packages (`penge/api`, `penge/web`) inherit public visibility from
the public `autoditac/Penge` repository, so the NAS pulls anonymously — no
registry credential is stored or rotated on the NAS for this path.
If the repository or its packages are ever made private, a read-only,
`read:packages`-scoped fine-grained PAT would need to be added to the
system's `containers-auth.json` (`podman login ghcr.io`); this is not
required today.

## Applying a quadlet change

1. Edit the applicable files in `deploy/nas/`, open a PR, get it reviewed and
   merged (same DoD as any other change).
2. Copy the merged quadlets to `/etc/containers/systemd/` and the nginx
   configuration to `/etc/nginx/conf.d/penge.eigmueller.de.conf` (root-owned).
3. `systemctl daemon-reload`
4. Validate nginx with `nginx -t`, then restart the changed
   `penge-{api,web}.service` units and reload nginx.
5. Confirm both containers report `healthy` with
   `podman inspect penge-api penge-web --format '{{.Name}} {{.State.Health.Status}}'`.

## Manual / immediate update

To pull the current `:main` image right away instead of waiting for the
daily timer:

```bash
sudo podman auto-update
```

Use `sudo podman auto-update --dry-run` first to see what *would* update
without making changes.

## Finding the running digest

```bash
journalctl -u penge-api.service -u penge-web.service -g 'digest=' --no-pager | tail -20
```

Each line looks like:

```text
penge-web deploy: 2026-09-20T19:30:00+02:00 digest=sha256:28beeef4...
```

The digest is the exact, immutable manifest digest GHCR resolved `:main` to
at that moment — it identifies the build precisely, independent of any tag
ever being reused or repointed.

## Migration coordination

Auto-deploy only replaces container images; it never runs Alembic.
A merge that changes both the schema and the API in the same PR
can therefore roll out to the NAS **before** its migration has been
applied, because the image update and the DB migration are not gated on
each other.

**Contract:** any PR that requires a new migration to be applied before its
API changes can run correctly must not rely on auto-deploy ordering.
Instead:

- Prefer the expand/contract pattern: land the migration (additive,
  backward-compatible with the *currently deployed* API) in its own PR
  first, apply it to the NAS (see below), confirm the running `:main`
  image still works against the new schema, and only then merge the PR
  that starts relying on it. Drop/narrow migrations (the "contract" step)
  follow once no deployed image reads the old shape anymore.
- If a single PR cannot reasonably be split that way, apply the migration
  to the NAS **manually, before merging**, using the workstation-over-SSH-tunnel
  method already documented in the
  [Enable Banking consent runbook](enable-banking-consent.md) (`DATABASE_URL=... uv run --group db alembic upgrade head`
  against the tunnelled NAS Postgres) -- the NAS has no repo checkout to
  run Alembic locally.

This is a manual, reviewed step by design: schema changes already require
a working `downgrade()` and (for destructive changes) an ADR per
`.github/instructions/migrations.instructions.md`; adding unattended
migration execution to the auto-update path would let an unreviewed
schema change run against production with no human in the loop, which is
a larger change warranting its own ADR if ever pursued.

## Rollback

Auto-update already rolls back automatically on a failed health check (see
above).
For a manual rollback — e.g. `:main` is healthy but produces wrong
application behaviour — pin the quadlet directly to the last known-good
**digest** from the journal (not a tag, so no lookup or guesswork is
needed):

1. Find the last known-good digest with the `journalctl` command above
   (the entry from before the bad deploy).
2. On the NAS, edit the affected `penge-{api,web}.container` file and change
   its `Image=...:main` reference to `Image=...@<digest>` (for example,
   `ghcr.io/autoditac/penge/web@sha256:28beeef4...`).
3. Run `systemctl daemon-reload` and restart the affected service.

Pinning to a digest also **stops** `AutoUpdate=registry` from doing
anything further (a fixed digest never changes), which is exactly what you
want while investigating a bad release.
Revert `Image=` back to `:main` (and reload/restart) once the fix has
merged and republished, to resume automatic updates.

## Scope

This covers the `penge-api` and `penge-web` containers.
PostgreSQL remains a host-managed quadlet pinned to a versioned image digest;
database upgrades follow the migration procedure above and are never automatic.
