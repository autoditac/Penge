# Runner maintenance (`gh-runner-ubuntu`)

Operational procedures for the self-hosted GitHub Actions runner that builds
Penge's container images. Its VM disk is ~19 GB, which is enough for CI only
if Docker's growth is actively bounded.

## The failure mode

CI builds images with `docker/setup-buildx-action`. The action starts a
BuildKit container named `buildx_buildkit_<builder>0`, backed by a **named**
volume `buildx_buildkit_<builder>0_state` holding the build cache.

On a normal job — including a failing one — the builder is removed twice over:
once by the action's own post-step (`cleanup` defaults to `true` at the pinned
SHA) and once by the workflow's `if: always()` teardown step.

Neither runs when a job dies abnormally:

- the runner service restarts or the host reboots,
- the job is OOM-killed,
- a cancellation outlives the runner's cancel timeout (`ci.yml` uses
  `cancel-in-progress: true`, so cancellations are routine),
- the disk is *already* full, so teardown itself fails.

The leaked BuildKit container then keeps **running**. A running container pins
its named volume, so `docker system prune -af --volumes` reports success while
reclaiming none of it. That is how the runner hit 100% disk twice: five stale
builders held 3.18 GB that ordinary pruning could not touch, and a full prune
recovered only 1.58 GB until the containers themselves were removed.

## What bounds it now

| Layer | Where | What it does |
| --- | --- | --- |
| Unique builder names | `ci.yml`, `release.yml` | `penge-<job>-<run_id>-<attempt>-<app>`, so a leak is attributable to a job and teardown never needs a step output. |
| Per-job teardown | `ci.yml`, `release.yml` | `if: always()` removal of that one builder, its container, its state volume, and the run-scoped `penge/<app>:ci-<run>` image. Scoped by name — never a blanket prune, which would destroy a concurrent matrix job's cache. |
| BuildKit GC | `buildkitd-config-inline` | Caps a single builder's cache at 2 GB, so even a leaked builder stops growing. |
| Host sweep | `penge-docker-gc.timer` | Hourly, **independent of GitHub Actions**, reclaims anything older than 2 h. This is the layer that still works when the runner is wedged. |
| Manual sweep | `runner-maintenance.yml` | Daily belt-and-braces run plus a dry-runnable `workflow_dispatch` lever. |

### Why age-bounding makes it concurrency-safe

Every removal in `deploy/runner/docker-gc.sh` is gated on a 2 h age threshold,
and the prunes use Docker's `until=` filter. The longest job timeout in the
repository is 30 minutes (`release.yml`), so a resource older than the
threshold provably cannot belong to a running job. There is no unconditional
`docker system prune` anywhere, and non-BuildKit containers are never matched.

## Installing the host units

Requires root on the runner VM. Run from a checkout of `main`:

```bash
sudo install -m 0755 deploy/runner/docker-gc.sh /usr/local/bin/penge-docker-gc
sudo install -m 0644 deploy/runner/penge-docker-gc.service /etc/systemd/system/
sudo install -m 0644 deploy/runner/penge-docker-gc.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now penge-docker-gc.timer
```

Verify:

```bash
systemctl list-timers penge-docker-gc.timer
sudo /usr/local/bin/penge-docker-gc --dry-run   # report only, removes nothing
sudo systemctl start penge-docker-gc.service    # one sweep now
journalctl -u penge-docker-gc.service -n 50
```

Re-run the `install` commands after changing the script or units in the repo;
they are tracked here, not edited in place on the host.

## Manual recovery (disk already full)

1. Confirm the diagnosis — look for `buildx_buildkit_*` containers that no
   running job explains:

   ```bash
   df -h /
   docker ps -a --filter name=buildx_buildkit_ --format '{{.Names}}\t{{.Status}}\t{{.CreatedAt}}'
   docker system df -v | head -40
   ```

2. Check the runner is actually idle before removing anything younger than a
   couple of hours:

   ```bash
   gh run list --repo autoditac/Penge --status in_progress
   ```

3. Sweep:

   ```bash
   sudo /usr/local/bin/penge-docker-gc --dry-run
   sudo /usr/local/bin/penge-docker-gc
   ```

   If the disk is so full that Docker itself misbehaves, lower the threshold
   only after confirming step 2 shows no in-progress runs:

   ```bash
   sudo /usr/local/bin/penge-docker-gc --max-age-hours 1
   ```

4. If the runner service died during the incident, restart it and re-run the
   affected workflow:

   ```bash
   sudo systemctl restart actions.runner.*.service
   gh run rerun <run-id> --repo autoditac/Penge
   ```

Without shell access, `Actions -> runner-maintenance -> Run workflow` performs
the same sweep (tick **dry-run** first). It needs a *working* runner, which is
why the systemd timer — not this workflow — is the authoritative schedule.

## What never to do here

- Never `docker system prune` unconditionally on this host: it takes running
  jobs' build caches with it and, as the incident showed, does not even
  reclaim the pinned volumes that caused the outage.
- Never delete a `buildx_buildkit_*` container younger than the threshold
  without checking `gh run list --status in_progress` first.
- Never edit the script or units directly on the host — change them in
  `deploy/runner/` and reinstall, so the next rebuild keeps the fix.

## Related

- [Container images](container-images.md) — what CI builds and publishes.
- [NAS deploy and rollback](nas-deploy.md) — the *deployment* host, a
  different machine with its own podman auto-update lifecycle.
