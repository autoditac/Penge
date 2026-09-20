# NAS deploy and rollback

How the `penge-api` container on the NAS (`penge.eigmueller.de`) stays current
with `main`, and how to roll it back.
See [ADR-0044](../decisions/0044-continuous-image-publishing-and-nas-auto-deploy.md)
for the design rationale.

## How it works

Every merge to `main` publishes `ghcr.io/autoditac/penge/api:main` and
`ghcr.io/autoditac/penge/api:<commit-sha>` (see the
[container images runbook](container-images.md)).

The NAS quadlet at `/etc/containers/systemd/penge-api.container` (tracked in
this repo at `deploy/nas/penge-api.container`) references the moving
`:main` tag and carries `AutoUpdate=registry`.

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

1. Edit `deploy/nas/penge-api.container` in this repo, open a PR, get it
   reviewed and merged (same DoD as any other change).
2. Copy the merged file to the NAS as
   `/etc/containers/systemd/penge-api.container` (root-owned).
3. `systemctl daemon-reload`
4. `systemctl restart penge-api.service`
5. Confirm health:
   `podman inspect penge-api --format '{{.State.Health.Status}}'`

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
journalctl -u penge-api.service -g 'digest=' --no-pager | tail -20
```

Each line looks like:

```text
penge-api deploy: 2026-09-20T11:55:18+02:00 digest=sha256:978cb42eb7e4bb7639bca66496171bd430748ee1114d6740621f1a16c47a3d6b
```

The digest is the exact, immutable manifest digest GHCR resolved `:main` to
at that moment — it identifies the build precisely, independent of any tag
ever being reused or repointed.

## Rollback

Auto-update already rolls back automatically on a failed health check (see
above).
For a manual rollback — e.g. `:main` is healthy but produces wrong
application behaviour — pin the quadlet directly to the last known-good
**digest** from the journal (not a tag, so no lookup or guesswork is
needed):

1. Find the last known-good digest with the `journalctl` command above
   (the entry from before the bad deploy).
2. On the NAS, edit `/etc/containers/systemd/penge-api.container` and change
   `Image=ghcr.io/autoditac/penge/api:main` to
   `Image=ghcr.io/autoditac/penge/api@<digest>` (e.g.
   `ghcr.io/autoditac/penge/api@sha256:978cb42e...`).
3. `systemctl daemon-reload && systemctl restart penge-api.service`

Pinning to a digest also **stops** `AutoUpdate=registry` from doing
anything further (a fixed digest never changes), which is exactly what you
want while investigating a bad release.
Revert `Image=` back to `:main` (and reload/restart) once the fix has
merged and republished, to resume automatic updates.

## Scope

This covers the `penge-api` container only.
The WebUI is currently served as static files from `/var/www/penge` by the
host's own nginx, not from the `penge/web` container image; bringing it onto
the same auto-update path is a separate follow-up (see ADR-0044).
