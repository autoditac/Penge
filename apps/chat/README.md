# Penge chat service

`@penge/chat` is the loopback-only multi-user Ask Penge backend from issue #346.
It binds an immutable Google oauth2-proxy subject to a separate per-user GitHub OAuth grant, runs the Copilot SDK in `mode: "empty"` with exact model `hydrafusion`, and exposes only accepted read-only Penge MCP tools over a local stdio child.

Production is deliberately disabled unless `PENGE_CHAT_ENABLE_PRODUCTION=1`.
Each actor's exact `hydrafusion` entitlement is checked by creating the SDK session with that actor's token provider; an unavailable-model failure is terminal and no fallback is configured.

## Trust boundaries

- The HTTP listener accepts only `127.0.0.1`, `localhost`, or `::1`.
- The reverse proxy must overwrite `X-Penge-Auth-Issuer`, `X-Penge-Auth-Subject`, and `X-Penge-Proxy-Secret`.
- State-changing requests require the configured application origin; chat and stop bodies require `application/json`.
- `X-Penge-Auth-Subject` is the immutable Google subject, not email or display name.
- The browser never supplies an actor or household-member ID.
- GitHub access and refresh tokens, OAuth state, and the PKCE verifier are encrypted with versioned AES-256-GCM envelopes.
- Per-actor PostgreSQL advisory locks serialize refresh and link changes across service processes.
- OAuth callback state deletion commits before exchange while the actor lock remains held, so failed callbacks cannot reuse one-time state.
- Unlink removes pending OAuth states and completes after any in-flight callback, then cancels active streams with a terminal event.
- Database waits are bounded, idle pool failures trigger controlled shutdown, and readiness probes share chat concurrency limits.
- Copilot session files are bounded process memory, persistent SDK workspaces are disabled, and teardown retains no prompt or transcript.
- Audit and request logs use fixed identifiers only; model-controlled argument names, values, and request paths are not retained.
- The `penge_chat_oauth` database role is checked at startup against the dedicated chat database and may access only the three chat tables.
- The finance MCP child receives only `PENGE_DB_URL_FILE`; database credentials are never rematerialized into its environment.

## Mounted secrets

Secret contents are never accepted directly from environment variables.
Podman mounts each secret as an owner-only (`0600`) regular file and supplies these paths:

| Variable                               | File contents                                                    |
| -------------------------------------- | ---------------------------------------------------------------- |
| `PENGE_CHAT_IDENTITY_PEPPER_FILE`      | At least 32 random characters used for actor/state HMAC          |
| `PENGE_CHAT_PROXY_SHARED_SECRET_FILE`  | At least 32 random characters also injected by the trusted proxy |
| `PENGE_CHAT_GITHUB_CLIENT_SECRET_FILE` | GitHub OAuth client secret                                       |
| `PENGE_CHAT_TOKEN_KEYRING_FILE`        | Versioned JSON keyring shown below                               |
| `PENGE_CHAT_DATABASE_URL_FILE`         | Dedicated OAuth database URL                                     |
| `PENGE_DB_URL_FILE`                    | Finance MCP database URL passed by file path to the child        |

```json
{
  "currentKeyId": "2026-10-v2",
  "keys": {
    "2026-09-v1": "<base64 32-byte retained key>",
    "2026-10-v2": "<base64 32-byte current key>"
  }
}
```

Rotate by adding the new key, changing `currentKeyId`, restarting, and retaining old keys until every stored envelope has been refreshed or re-encrypted.

## Non-secret configuration

Required values include `PENGE_CHAT_MODEL=hydrafusion`, proxy issuer, GitHub client ID, MCP working/log/vault paths, Copilot base directory, and `PENGE_CHAT_MCP_TOOL_CONTRACT_VERSION=issue-344-v1`.
`PENGE_CHAT_PUBLIC_API_BASE` is the trailing-slash external HTTPS API base and may contain a proxy prefix such as `https://host/ask/api/`.
`PENGE_CHAT_PUBLIC_APP_ORIGIN` contains only the external browser origin used to redirect to `/ask`.
Both are intentionally separate from the loopback-only `PENGE_CHAT_HTTP_HOST`.

## Browser API

All routes except `/health` require the trusted proxy headers.

| Method   | Route                    | Result                                                                                                                   |
| -------- | ------------------------ | ------------------------------------------------------------------------------------------------------------------------ |
| `GET`    | `/v1/auth/status`        | `{github:{state,login},model:{id:"hydrafusion",available},featureEnabled}`                                               |
| `GET`    | `/oauth/github/start`    | Redirect to GitHub OAuth with one-time state and S256 PKCE                                                               |
| `GET`    | `/oauth/github/callback` | Consume state and redirect to `<PENGE_CHAT_PUBLIC_APP_ORIGIN>/ask?github=linked`                                         |
| `DELETE` | `/v1/auth/github`        | Delete the actor's OAuth link and invalidate cached model availability                                                   |
| `POST`   | `/v1/chat`               | Ask Penge `1.0` SSE; response header `X-Penge-Chat-Session-Id` identifies the immediately registered actor-owned session |
| `POST`   | `/v1/chat/stop`          | Stop only the authenticated actor's session                                                                              |

The schema-only chat migration has its own Alembic configuration at `apps/chat/alembic.ini`.
Database and role creation, grants, backup, and restore remain deployment-owned; the global finance Alembic chain never creates chat tables or alters chat-role privileges.

See [ADR-0055](../../docs/decisions/0055-isolated-multi-user-chat-runtime.md) and the [chat runtime runbook](../../docs/runbook/chat-runtime.md).
