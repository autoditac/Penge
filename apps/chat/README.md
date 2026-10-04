# Penge chat service

`@penge/chat` is the loopback-only multi-user Ask Penge backend from issue #346.
It binds an immutable Google oauth2-proxy subject to a separate per-user GitHub OAuth grant, runs the Copilot SDK in `mode: "empty"` with exact model `hydrafusion`, and exposes only accepted read-only Penge MCP tools over a local stdio child.

Production is deliberately unavailable unless both production gates are `1` and the linked user's `listModels()` response contains exactly `hydrafusion`.
No fallback model is configured.

## Trust boundaries

- The HTTP listener accepts only `127.0.0.1`, `localhost`, or `::1`.
- The reverse proxy must overwrite `X-Penge-Auth-Issuer`, `X-Penge-Auth-Subject`, and `X-Penge-Proxy-Secret`.
- `X-Penge-Auth-Subject` is the immutable Google subject, not email or display name.
- The browser never supplies an actor or household-member ID.
- GitHub access and refresh tokens, OAuth state, and the PKCE verifier are encrypted with versioned AES-256-GCM envelopes.
- Copilot, MCP, and HTTP teardown paths retain no prompt or transcript.
- The `penge_chat_oauth` database role is checked at startup and may access only the three chat tables.

## Mounted secrets

Secret contents are never accepted directly from environment variables.
Podman mounts each secret as an owner-only (`0600`) regular file and supplies these paths:

| Variable                               | File contents                                                    |
| -------------------------------------- | ---------------------------------------------------------------- |
| `PENGE_CHAT_IDENTITY_PEPPER_FILE`      | At least 32 random characters used for actor/state HMAC          |
| `PENGE_CHAT_PROXY_SHARED_SECRET_FILE`  | At least 32 random characters also injected by the trusted proxy |
| `PENGE_CHAT_GITHUB_CLIENT_SECRET_FILE` | GitHub OAuth client secret                                       |
| `PENGE_CHAT_TOKEN_KEYRING_FILE`        | Versioned JSON keyring shown below                               |

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

Required values include `PENGE_CHAT_MODEL=hydrafusion`, `PENGE_CHAT_PUBLIC_ORIGIN`, proxy issuer, GitHub client ID, chat and MCP database paths, MCP working/log/vault paths, Copilot base directory, and `PENGE_CHAT_MCP_TOOL_CONTRACT_VERSION=issue-344-v1`.
`PENGE_CHAT_PUBLIC_ORIGIN` is the exact external HTTPS origin used for OAuth callbacks; it is intentionally separate from `PENGE_CHAT_HTTP_HOST`.

See [ADR-0055](../../docs/decisions/0055-isolated-multi-user-chat-runtime.md) and the [chat runtime runbook](../../docs/runbook/chat-runtime.md).
