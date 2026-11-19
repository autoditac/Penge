# Chat runtime operations

The Ask Penge chat service is local-only and feature-disabled by default.
It must not be enabled merely because configuration exists.

## Enablement gate

For each linked household actor:

1. Complete GitHub OAuth using that person's own GitHub identity.
2. Verify an exact `hydrafusion` session with that actor's token provider reports one matching model with an explicitly enabled policy through the session-scoped model list.
3. Confirm issue #344's `issue-344-v1` MCP contract is installed.
4. Confirm the MCP accepts file-only `PENGE_DB_URL_FILE` configuration.
5. Run `just chat-check` and `just chat-migration-integration`, plus process-cleanup checks.
   The integration test needs `PENGE_CHAT_MIGRATION_TEST_ADMIN_URL` for a disposable PostgreSQL superuser; it creates uniquely suffixed databases and roles, refuses to reuse existing names, and drops only resources it created.
   The lock-contention regression uses the normal five-second database timeout and a fifteen-second test deadline, so startup privilege checks do not inherit an artificially short timeout.
6. Confirm an accepted ADR amends [ADR-0005](../decisions/0005-llm-access-via-mcp-only.md) for bounded transaction-level records reaching `hydrafusion`, or that the transaction search/detail tools are removed from the chat allowlist.
7. Set `PENGE_CHAT_ENABLE_PRODUCTION=1`.

If any step fails, keep the production gate unset or `0`.
Never substitute another model.

## Readiness and failure behavior

`GET /health` is quota-free and reports whether the feature is enabled.
Production startup connects to a process-local Penge MCP child, verifies the exact registration set (including `_meta`) and every output schema with `listTools`, and closes the probe.
The SDK exposes only the reviewed chat subset, never `_meta`.
Missing or extra MCP tools fail startup.
Each authenticated status check and chat launch verifies a fresh session-scoped model list using the linked actor token.
Missing, disabled, unconfigured, or duplicate model-policy entries fail closed.
Shutdown stops new chat and readiness admission, disconnects clients, and drains in-flight request handlers and runtime cleanup before closing the chat store.

GitHub OAuth grant rejection and a rejected user token report authentication expiry.
A token refresh rejected during a status probe or chat launch reports authentication expiry (HTTP 401 or non-retryable stream `auth_expired`), even though the SDK wraps the token-provider failure.
GitHub outages, rate limits, invalid responses, and OAuth configuration errors report an upstream failure instead; do not ask users to relink solely because of an upstream failure.

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
