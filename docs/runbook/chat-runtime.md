# Chat runtime operations

The Ask Penge chat service is local-only and feature-disabled by default.
It must not be enabled merely because configuration exists.

## Enablement gate

For each linked household actor:

1. Complete GitHub OAuth using that person's own GitHub identity.
2. Verify the token-safe `listModels()` result contains the exact ID `hydrafusion`.
3. Confirm issue #344's `issue-344-v1` MCP contract is installed.
4. Run the package tests, build, lint, migration round trip, and process-cleanup checks.
5. Set `PENGE_CHAT_HYDRAFUSION_ENTITLEMENT_VERIFIED=1` and `PENGE_CHAT_ENABLE_PRODUCTION=1`.

If any step fails, keep both gates unset or `0`.
Never substitute another model.

## Readiness and failure behavior

`GET /health` is quota-free and reports whether the feature is enabled.
Production startup connects to a process-local Penge MCP child, verifies all accepted tool names with `listTools`, and closes the probe.
Missing HydraFusion entitlement returns `hydrafusion_unavailable`; missing MCP tools fail startup.

## Incident response

1. Set `PENGE_CHAT_ENABLE_PRODUCTION=0` and restart the local service.
2. Confirm no Copilot or MCP child remains after the configured timeout.
3. Inspect only redacted JSON service metadata and `chat_audit_event`.
4. Do not request, export, or reconstruct prompts or transcripts; they are intentionally unavailable.
5. Revoke the affected actor's GitHub OAuth grant if credential compromise is suspected.
6. Rotate the token keyring by adding a current key while retaining prior decryption keys.

## Reverse-proxy contract

The infrastructure from issue #342 must remove client-supplied identity headers and set:

- `X-Penge-Auth-Issuer` to the exact configured Google issuer.
- `X-Penge-Auth-Subject` to the immutable Google `sub`.
- `X-Penge-Proxy-Secret` from the same mounted secret consumed by the chat service.

The proxy routes the authenticated external HTTPS callback to the loopback listener.
MCP, Copilot runtime, database, and raw tool ports remain unexposed.
