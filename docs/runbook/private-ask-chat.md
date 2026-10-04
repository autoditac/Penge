# Private Ask Penge chat deployment

This runbook covers the loopback-only private Ask Penge chat deployment behind the existing NAS nginx + oauth2-proxy boundary.
It is intentionally deployment-only: the underlying chat service, OAuth integration, and MCP tool contracts live in the app-specific implementation sessions, while the hosting seam stays here.

## Network boundary

- The chat container runs as `penge-chat` on the Podman `penge` network.
- It binds only to `127.0.0.1:8123` on the host and never publishes any port to the external network.
- The host nginx route is the only public entry point and remains behind the existing Google oauth2-proxy trust boundary.
- No public MCP listener, external Copilot runtime port, or raw database port is exposed.

## Podman secret setup

Create the secret-bearing files on the NAS host and then mount them into the quadlet as Podman secrets.
Do not commit the actual values to the repo.

```bash
sudo install -d -o root -g root -m 0700 /etc/penge
sudo podman secret create penge-github-oauth /etc/penge/penge-github-oauth
sudo podman secret create penge-chat-token-key /etc/penge/penge-chat-token-key
```

The tracked quadlet references the mounted secrets at `/run/secrets/...`.
The app-side implementation must load them as `ASK_PENGE_GITHUB_OAUTH_FILE` and `ASK_PENGE_TOKEN_KEY_FILE` and must never log raw token or OAuth values.

## Deploying the chat quadlet

```bash
sudo install -o root -g root -m 0644 \
  deploy/nas/penge-chat.container \
  /etc/containers/systemd/
sudo systemctl daemon-reload
sudo systemctl restart penge-chat.service
sudo podman inspect penge-chat --format '{{.State.Health.Status}}'
```

The health endpoint is expected to answer on `/readyz` and must be authorized behind oauth2-proxy before any chat routing is considered healthy.

## Nginx routing

The host nginx config keeps `/ask` under the existing OAuth trust boundary and overwrites forwarded identity headers rather than trusting any client-provided values.
The route uses the same `X-Forwarded-User` / `X-Forwarded-Email` pattern as the rest of the site and includes a restrictive `Content-Security-Policy` for streaming chat responses.

## Rollback and restore

- Use the last known-good `Image=` digest in the quadlet to restore a prior working revision.
- Confirm the image digest with `podman inspect penge-chat --format '{{.Image}}'` and `podman image inspect ... --format '{{.Digest}}'`.
- Roll back by editing the tracked quadlet in the repo, shipping the PR, and re-installing the unit on the NAS.
- Keep the transcript volume and the encrypted secret-backed state isolated from the chat runtime mount; do not persist transcripts on the host filesystem.

## Secret rotation

1. Rotate the GitHub OAuth secret and any AES-GCM key material.
2. Update the Podman secret values on the host without changing the tracked secret names.
3. Restart the chat service.
4. Validate the OAuth callback and a synthetic two-user flow still works.

## Incident response

- If the app is unhealthy, inspect `journalctl -u penge-chat.service --since 30min ago --no-pager`.
- If there is a loopback exposure or auth-related issue, disable the Nginx route first, then restart the chat service after verifying the secret mount is still valid.
- Do not repurpose the private-chat route for public MCP tooling, raw Copilot runtime access, or file-system access.
