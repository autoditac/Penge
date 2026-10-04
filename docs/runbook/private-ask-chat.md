# Private Ask Penge chat deployment

This runbook owns only packaging, deployment, and acceptance for the private Ask Penge chat in #342.
Application, WebUI, MCP source-coverage, and foundational security contracts belong to #343–#346.
See [ADR-0054](../decisions/0054-private-ask-chat-deployment.md).

## Current status: blocked and fail closed

Do not deploy the chat from this branch.

- `apps/chat` and its image do not exist on this branch.
- `deploy/nas/penge-chat.container.in` is intentionally non-loadable.
- `deploy/nas/penge-chat.nginx.conf.in` is intentionally non-loadable.
- `deploy/nas/penge-chat-db-role.sql.in` is intentionally non-executable.
- The active nginx configuration returns `404` for exactly `/ask` and the bounded `/ask/` prefix.
- `deploy/nas/validate-private-ask-chat.sh --ready` must fail while any `@@...@@` token remains.
- No NAS deployment, real account linking, HydraFusion call, or two-account acceptance has been performed.

The secure seam check is available through the repository task runner:

```bash
just private-ask-chat-deploy-check
```

It proves only that the unresolved deployment remains closed.
It is not deployment or acceptance evidence.

## Fixed security contract

The #345 architecture contract fixes these requirements:

- `@github/copilot-sdk` is exactly version `1.0.16`.
- The SDK runs in `mode: "empty"`.
- `PENGE_CHAT_MODEL=hydrafusion` is exact and has no fallback.
- Each Penge identity links a separate GitHub account and Copilot entitlement.
- Penge MCP runs only as a process-local stdio child.
- Default, shell, filesystem, arbitrary SQL, web-fetch, mutation, and public MCP tools are absent.
- Answers are explanation-first and grounded in typed, bounded, read-only evidence.
- Production remains disabled until HydraFusion entitlement is verified externally for each authorized identity without recording private prompt or response content.

The stable model assignment is tracked in `deploy/nas/private-ask-chat.contract.env.in`.
Unknown environment names remain tokens instead of guessed defaults.
The rootless service also requires `%h/.config/penge/private-ask-chat.approval.manifest`.
Do not create that manifest until every readiness and acceptance item below has evidence and an identified reviewer records an approving GitHub review.

## Packaging and CI gate

`.github/workflows/private-ask-chat-deployment.yml` runs deployment tests and the seam validator.
CI requires the unresolved seam to remain non-deployable until the release workflow publishes an attested image digest.
It must not infer readiness merely from the presence of `apps/chat/package.json`.
When the image integration lands, replace the seam step with an explicit dependency on the image build/attestation job and pass that job's exact digest as `PENGE_CHAT_IMAGE_DIGEST` to `--ready`.
The ready gate then requires all of the following:

1. All Quadlet, nginx, database, and environment contract tokens except the deployment-time image digest are resolved.
2. `apps/chat/Containerfile` exists.
3. Every base image is pinned by digest.
4. The committed `pnpm-lock.yaml` is used with `--frozen-lockfile`.
5. `apps/chat/package.json` pins `@github/copilot-sdk` exactly to `1.0.16`.
6. The repository image workflow builds, scans, publishes, and attests the chat image, then supplies its exact digest as `PENGE_CHAT_IMAGE_DIGEST` to `--ready`.

Do not weaken the gate to make an integration branch green.
Integrate the exact dependent contracts instead.

## Rootless ownership model

The chat is deliberately different from the existing root-managed API and WebUI Quadlets.
It runs as a dedicated unprivileged NAS account and is managed with `systemctl --user` and rootless `podman`.
The installer deliberately uses `$HOME/.config` for both rendered files and Quadlet `%h/.config` references; it does not honor `XDG_CONFIG_HOME`.

A root administrator must enable and verify lingering once for the dedicated account so its user manager starts at boot and survives logout:

```bash
sudo loginctl enable-linger penge-chat
loginctl show-user penge-chat --property=Linger --value
```

The verification output must be exactly `yes`.
This is host provisioning, not an action performed by this PR.

The final rendered unit belongs at:

```text
~/.config/containers/systemd/penge-chat.container
```

The template publishes only `127.0.0.1:8123`.
It has no public MCP, Copilot runtime, database, raw-tool, health, or metrics port.
It uses a read-only root filesystem, a bounded temporary filesystem, default SELinux confinement, no new privileges, and no Linux capabilities.
There is no persistent chat volume while the backend storage contract is unknown.

The installer refuses root execution, mutable tags, wildcard binds, missing secrets, missing or stale approval, unsafe ownership or permissions, and unresolved contract tokens.
Once the contracts are resolved and reviewed, render an exact image digest without the `sha256:` prefix:

```bash
deploy/nas/install-private-ask-chat-quadlet.sh \
  0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
```

This example digest is synthetic and must never be deployed.
The installer only renders and reloads the user service; it does not enable or start it.

### Reviewed approval manifest

Both `private-ask-chat.contract.env` and `private-ask-chat.approval.manifest` must:

- be regular files, not symlinks;
- be owned by the dedicated rootless service UID; and
- use exactly mode `0400` or `0600`.

The version-1 manifest contains exactly one value for each field:

```text
version=1
decision=approved
reviewed_by=<GitHub reviewer login>
review_reference=https://github.com/autoditac/Penge/pull/<number>#pullrequestreview-<id>
image_digest=<64 lowercase hexadecimal characters>
contract_env_sha256=<sha256>
quadlet_template_sha256=<sha256>
rendered_quadlet_sha256=<sha256>
nginx_template_sha256=<sha256>
database_template_sha256=<sha256>
contract_env_template_sha256=<sha256>
```

The reviewer calculates the hashes from the exact files and rendered Quadlet they reviewed.
The installer rejects missing, duplicate, unknown, empty, malformed, or mismatched fields.
The private environment file must match the fully resolved, reviewed environment template byte for byte; missing, duplicate, reordered, or additional assignments are rejected even when their file hash appears in the manifest.
It copies the approved environment to a private hash-addressed path, and the rendered Quadlet references only that snapshot.

Any image digest, environment, Quadlet, nginx, database, or environment-template change invalidates the manifest.
Create a new manifest and obtain a new review; never update hashes under an old review reference.

## Versioned Podman secrets

Do not update a Podman secret in place.
Create a new versioned secret, switch the reviewed Quadlet contract, restart, verify, and only then retire the old version.

The final unit requires three rootless secrets:

- GitHub OAuth application material.
- A versioned AES-GCM token-encryption keyring.
- The least-privilege chat database URL.

Exact payload formats and mount targets come from #346 and remain unresolved tokens.
The image-owned container UID/GID and rootless network topology also remain unresolved rather than assuming UID `1000` or host-loopback database access.
Create secrets only as the dedicated chat account and only after that contract lands:

```bash
umask 077
podman secret create penge-chat-github-oauth-v2 /secure/path/github-oauth-v2
podman secret create penge-chat-token-keyring-v2 /secure/path/token-keyring-v2
podman secret create penge-chat-database-url-v2 /secure/path/database-url-v2
```

Never pass a secret value on the command line, in an environment variable, or through shell history.
Delete the source file from the NAS staging location after confirming the rootless secret exists.

### AES-GCM key rotation

1. Back up the active keyring through the approved encrypted secret-backup channel.
2. Create a new keyring version containing the old decrypt-only key and the new active encrypt key.
3. Change the reviewed Quadlet secret reference without deleting the old Podman secret.
4. Restart the user service and verify old tokens decrypt while all newly written tokens carry the new key version.
5. Run the #346 migration or re-encryption procedure and verify no rows retain the old key version.
6. Exercise rollback with the prior image and compatible dual-key keyring.
7. Retire the old key from the keyring and remove the old Podman secret only after the rollback window closes.

The infrastructure change does not define keyring JSON, ciphertext, nonce, or migration formats.
Those are backend contracts and must not be inferred here.

### OAuth client rotation and unlinking

Create a new versioned OAuth secret and update the GitHub callback configuration before switching the Quadlet reference.
Keep the previous secret until callback, state, PKCE, refresh, and separate-user tests pass.

Account unlinking must revoke the GitHub grant where supported and delete only that identity's OAuth-link rows.
It must not remove another user's link, finance data, audits, or shared source data.
Use the backend-owned unlink operation once #346 provides it; do not manipulate ciphertext manually.

## Dedicated OAuth database and least-privilege role

`deploy/nas/penge-chat-db-role.sql.in` is non-executable until #346 supplies migration-owned identifiers.
The resolved template must target a dedicated chat OAuth database and abort when connected to any other database.
The resolved SQL may grant only:

- `CONNECT` on the dedicated chat OAuth database.
- `USAGE` on the OAuth-link schema.
- `SELECT`, `INSERT`, `UPDATE`, and `DELETE` on the explicit OAuth-link tables.

It must not grant schema creation, default privileges, sequence-wide access, finance or analytics reads, transcript storage, MCP access, ownership, role inheritance, or superuser capabilities.
Its `PUBLIC` revocations apply only inside that dedicated database.
Chat deployment must not change the shared Penge finance database or any API, dbt, ingestion, migration, backup, or maintenance role privileges.

If #346 instead mandates same-database storage, remove this provisioning template and place the exact grants in its reversible migration.
Do not adapt this deployment seam to revoke shared-database privileges.
Apply it through the reviewed database administration path only after `--ready` passes, then query PostgreSQL privileges and attach the redacted result to the acceptance record.

## Nginx trust boundary

The active host config currently denies `/ask` and `/ask/…`.
It does not prefix-match `/askevil`.

The candidate route template:

- uses the existing Google oauth2-proxy `auth_request` boundary;
- overwrites user, email, and client-identity headers from oauth2-proxy values;
- never trusts client-supplied identity headers;
- limits routing to exact `/ask` and bounded `/ask/`;
- contains no `script-src 'unsafe-inline'`;
- disables caching of private responses; and
- leaves base-path and streaming behavior unresolved until #343 and #346 publish exact semantics.

Do not copy the candidate into the live nginx config while any token remains.
Validate with `nginx -t` before every reload.

## Health, readiness, metrics, and logs

The container health command remains unresolved because the runtime image and endpoints are not yet defined.
The final contract must distinguish:

- liveness that consumes no model quota;
- readiness that verifies the SDK runtime, exact HydraFusion availability and entitlement, local MCP metadata, complete source coverage, database role, and bounded process cleanup; and
- public request handling, which remains behind oauth2-proxy.

An unavailable or unauthorized HydraFusion model makes readiness fail.
There is no fallback model and no degraded success response.
Incomplete required source coverage also makes readiness fail.

Metrics must remain loopback or process-local and must contain only bounded counts, durations, statuses, and redacted error codes.
Logs must be structured and must exclude prompts, answers, transcript content, OAuth tokens, cookies, authorization headers, raw tool arguments, account identifiers, and financial values.
Use pseudonymous actor and session identifiers only.

## Backup and restore

The dedicated chat OAuth database requires its own encrypted logical backup.
The existing finance-database backup does not include it.
Store its URL in the NAS secret manager or an encrypted systemd credential readable only by the backup service account.
Use that mechanism to launch a restricted backup shell with `DATABASE_URL` already loaded for the child process; never type, paste, or interpolate the URL at the prompt.
After #346 adds a collision-safe chat backup label/path, the visible command is only:

```bash
just backup --label chat-oauth-pre-change
```

The AES-GCM keyring is not useful inside the database backup and must be backed up separately through the approved encrypted secret channel.
A database restore without the matching historical decrypt keys is incomplete.
A key backup without the encrypted database is also incomplete.

For a restore drill:

1. Restore the dedicated OAuth backup into an isolated chat OAuth test database.
2. Provision a disposable copy of the matching versioned keyring.
3. Start only the synthetic backend against the restored database.
4. Verify synthetic OAuth links decrypt and remain identity-isolated.
5. Verify no transcript content is present.
6. Destroy the disposable database and secrets.

Never test restore against production and never use real financial or OAuth data in CI.

## Digest rollback

Record the running digest from the rootless service journal:

```bash
journalctl --user -u penge-chat.service -g 'digest=' --no-pager
```

Rollback is an explicit re-render of the last known-good digest.
There is no tag-based auto-update.
Before restart, verify that the old image is compatible with the current database schema, environment contract, and keyring versions.
Keep both the previous image digest and compatible secret versions through the rollback window.

```bash
deploy/nas/install-private-ask-chat-quadlet.sh \
  aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
systemctl --user restart penge-chat.service
```

The example is synthetic.
Use only a recorded GHCR manifest digest with verified provenance.

## Acceptance evidence

CI may use synthetic identities and streams.
Real acceptance requires explicit authorization from both account holders and must use two separately entitled GitHub/Copilot identities.
Do not record prompt text, answer text, tokens, cookies, account identifiers, or financial values in the evidence.

The signed acceptance record must include pass/fail, timestamp, image digest, test version, and redacted correlation IDs for:

1. Separate allowlisted Penge identities and separate GitHub OAuth grants.
2. Cross-user token, session, reconnect, and evidence isolation.
3. Exact HydraFusion entitlement and explicit unavailable/unauthorized failure with no fallback.
4. Complete required source coverage before startup.
5. Streaming order, cancellation propagation, disconnect cleanup, and reconnect semantics.
6. OAuth state, PKCE, callback mismatch, expiry, refresh failure, unlink, and revoked-grant failures.
7. Local stdio MCP only, absent default tools, and rejected mutation, shell, filesystem, web-fetch, arbitrary SQL, and raw-statement access.
8. External-port scan showing only the intended HTTPS edge and loopback chat port.
9. Restart showing no transcript persistence and no orphan SDK or MCP process.
10. Quota-free liveness, fail-closed readiness, privacy-safe metrics, and redacted logs.
11. Backup/restore, key rotation, unlink, digest rollback, and rollback-compatible keyring.

Synthetic tests are not evidence of real HydraFusion entitlement.
Real account acceptance is not complete until both authorized users participate.

## External network and persistence checks

Run these only on the NAS after the gate is resolved:

```bash
systemctl --user status penge-chat.service --no-pager
podman port penge-chat
ss -ltnp
podman inspect penge-chat \
  --format '{{json .HostConfig.PortBindings}} {{json .Mounts}}'
podman diff penge-chat
```

The evidence must show:

- host port `8123` bound only to `127.0.0.1`;
- no host bind for the container HTTP target, MCP, Copilot runtime, database, health, or metrics;
- no writable persistent mount for transcripts;
- only the declared read-only MCP mount and secret mounts; and
- no transcript file created before or after a service restart.

From a separate machine, scan the NAS and prove that `8123`, the container HTTP target, and all MCP/runtime candidate ports are closed.
Record only port numbers and open/closed state.

## NAS deployment checklist

Do not create the approval manifest until every item is true.

- [ ] #343–#346 exact contracts are merged into this branch.
- [ ] `validate-private-ask-chat.sh --ready` passes.
- [ ] Chat package and lockfile pin `@github/copilot-sdk` `1.0.16`.
- [ ] Chat image CI, SBOM, provenance, vulnerability checks, and exact GHCR digest pass.
- [ ] Source-coverage startup gate includes every source required by #344.
- [ ] HydraFusion entitlement is externally verified for both authorized identities with no fallback.
- [ ] Dedicated OAuth database migration round-trip and explicit OAuth-table grants pass without changing finance-database or global-role privileges.
- [ ] Versioned rootless secrets exist and encrypted backups are verified.
- [ ] Nginx exact/bounded routes pass `nginx -t` behind oauth2-proxy.
- [ ] Container runs rootless with loopback-only publishing and default SELinux confinement.
- [ ] `loginctl show-user penge-chat --property=Linger --value` returns `yes`.
- [ ] Liveness/readiness, logs, and metrics meet the privacy contract.
- [ ] Synthetic two-user, OAuth failure, streaming, cancel, reconnect, and cleanup tests pass.
- [ ] Authorized two-user acceptance is recorded without private content.
- [ ] External scan and restart/no-transcript evidence pass.
- [ ] Backup/restore, key rotation, unlink, and digest rollback drills pass.
- [ ] Previous digest and compatible secret versions remain available for rollback.
- [ ] The reviewed approval manifest binds the exact digest, environment, rendered unit, and all template hashes after all evidence is attached.

## Incident response

Keep the route closed or restore the nginx `404` blocks first.
Then stop the rootless user service:

```bash
systemctl --user disable --now penge-chat.service
journalctl --user -u penge-chat.service --since '30 minutes ago' --no-pager
```

Do not paste logs into an issue until they have been checked for private content.
Preserve only redacted status and correlation metadata needed for diagnosis.
