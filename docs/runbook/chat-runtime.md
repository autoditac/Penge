# Chat runtime operations

The Ask Penge chat service is local-only and feature-disabled by default.
It must not be enabled merely because configuration exists.

## Enablement gate

For each linked household actor:

1. Complete GitHub OAuth using that person's own GitHub identity.
2. Start a session with that actor's token provider and verify exact-model session creation succeeds for `hydrafusion`.
3. Confirm issue #344's `issue-344-v1` MCP contract is installed.
4. Confirm the MCP accepts file-only `PENGE_DB_URL_FILE` configuration.
5. Run `just chat-check` and `just chat-migration-integration`, plus process-cleanup checks.
6. Set `PENGE_CHAT_ENABLE_PRODUCTION=1`.

If any step fails, keep the production gate unset or `0`.
Never substitute another model.

## Readiness and failure behavior

`GET /health` is quota-free and reports whether the feature is enabled.
Production startup connects to a process-local Penge MCP child, verifies the exact registration set (including `_meta`) and every output schema with `listTools`, and closes the probe.
The SDK exposes only the reviewed chat subset, never `_meta`.
Missing or extra MCP tools fail startup.
Per-actor model availability remains false until exact `hydrafusion` session creation succeeds with the linked actor token.

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

The proxy must preserve the configured trailing-slash `PENGE_CHAT_PUBLIC_API_BASE`, including any path prefix.
The browser page redirect uses the separate path-free `PENGE_CHAT_PUBLIC_APP_ORIGIN`.

## Dedicated database migration

The chat OAuth schema is not part of the finance Alembic graph.
Deployment creates the dedicated database and restricted login role, then an owner runs:

```bash
PENGE_CHAT_MIGRATION_DATABASE_URL_FILE=/run/secrets/chat-migration-db-url-v1 \
  uv run --group db --group http alembic -c apps/chat/alembic.ini upgrade head
```

Downgrade removes only chat-owned tables.
It never creates, drops, grants, or revokes cluster roles, databases, or finance privileges.
