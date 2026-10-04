# Chat safety gate and feature-disable runbook

This runbook covers the first architecture-proof layer for the Penge chat surface. It is intentionally conservative: the feature stays disabled unless the exact external gate is proven for the authenticated user and Copilot plan.

## Required contract

The runtime must enforce the following:

- `mode: "empty"`
- `PENGE_CHAT_MODEL=hydrafusion`
- no `PENGE_CHAT_FALLBACK_MODEL`
- `PENGE_CHAT_ENABLE_PRODUCTION=1` before production use
- separate GitHub and Copilot identity values
- local stdio MCP only with `allowlist` entries for the Penge tools
- blocked ambient tools: `shell`, `filesystem`, and `default`

## Safety checks

Before enabling the feature in production, confirm all of the following:

1. The authenticated GitHub account and the Copilot account are distinct identities.
2. The user has the correct Copilot plan and HydraFusion entitlement.
3. The model selection matches the documented app contract and not a fallback model.
4. The session is created with `mode: "empty"` and user-scoped tokens.
5. The MCP server is still the single data-access layer; no raw database or shell access is exposed.

If any check fails, keep the feature off and return to the synthetic, disabled-by-default contract in `apps/mcp/src/chat.ts`.

## Local validation

```bash
just mcp-chat-proof
```

This runs the synthetic harness that proves the empty-mode contract, the stream event shapes, the tool allowlist, blocked ambient tools, and the no-fallback policy. The harness intentionally uses synthetic fixtures only.

## External gate

The exact HydraFusion entitlement check is outside the repository boundary. The SDK docs describe backend server mode and per-user tokens, but they do not provide a stable server-side model ID we can safely query without exposing the authenticated user's token or financial data. Because of that, the repository keeps the feature disabled unless the user proves the entitlement externally and configures the production gate explicitly.

This is the safe default for a private household-finance application.
