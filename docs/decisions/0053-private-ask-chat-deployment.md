# 0053. Private Ask Penge chat deployment seam

- Status: Accepted
- Date: 2026-10-04

## Context

The parent feature (#341) introduces a private Ask Penge chat that is grounded in the Penge MCP tool surface and authenticates through GitHub/Copilot identities.
The app work is split across implementation sessions for the service, WebUI, and evidence paths, but the deployment surface remains a repository-owned concern.
The host must keep all public exposure behind the existing NAS nginx + oauth2-proxy boundary, with strict loopback-only access for the runtime itself.

## Decision

We keep the private Ask Penge chat behind the existing `penge.eigmueller.de` host, served through the same Google OAuth trust boundary as the rest of the application.
The actual runtime stays local to Podman on the NAS, publishes only a loopback port to the host, and mounts secrets and read-only MCP state through Podman secret and volume mechanisms.

We do not expose any public MCP listener or Copilot runtime port.
The Nginx route overwrites forwarded identity headers from oauth2-proxy rather than trusting any client-supplied values.
The deployment seam includes health `/readyz`, digest logging, and a secret-backed configuration contract for the chat runtime, but deliberately leaves the underlying app implementation to the app-specific workstreams.

## Consequences

### Positive

- No public edge exposure for the MCP or Copilot runtime.
- Deployment is reproducible and reviewable in the repo.
- Secret material stays in Podman secrets instead of environment files.
- Rollback and digest tracking remain aligned with the existing NAS deploy model.

### Negative

- The runtime cannot be reached directly on a public port.
- App-specific routing and tool contracts must be validated by the adjacent feature workstreams before full acceptance is claimed.
