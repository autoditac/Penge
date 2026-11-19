# Chat architecture proof and production gate

Issue #345 supplies a synthetic architecture proof, not a live chat service.
Production remains disabled because the currently authenticated user's
`listModels()` response did not contain the exact `hydrafusion` ID and the
transaction-level tools require owner acceptance of the proposed ADR-0005
amendment from #390.

## Validate the synthetic proof

```bash
just chat-feasibility
just mcp-test
```

The first recipe builds, tests, and lints `@penge/chat-feasibility`.
It proves the pinned SDK configuration shape, empty mode, streaming event
schemas, local stdio MCP configuration for the 16 implemented model tools,
ambient-tool denial, actor/token/storage ownership, sanitized child
environments, and typed unavailable-model errors.
It uses synthetic values and makes no external model call.
It does not start the MCP child, request `tools/list`, or invoke a tool.
The MCP test separately spawns a synthetic stdio server using the production
registry and a fake query runner, lists its read-only tools, and invokes
`query_net_worth` with synthetic input.
This does not test the production entrypoint or a Copilot session.

The landed `issue-344-v1` MCP server registers `_meta` plus 16 chat tools.
The independent stdio `tools/list` test proves the exact 17-name set using
the same tool factory as the production entrypoint, including output schemas.
This proves registration, not permission to expose the 16 tools to a model.
The synthetic SDK configuration includes all 16 tools, but production must
remain disabled: `search_household_transactions` and
`get_household_transaction_detail` must not reach a live model until the
owner accepts the proposed
[ADR-0005](../decisions/0005-llm-access-via-mcp-only.md) amendment or those
tools are removed; `_meta` remains protocol-only.

## Run the token-safe entitlement check

```bash
just chat-entitlement-check
```

Before running, supply `PENGE_CHAT_DIAGNOSTIC_GITHUB_TOKEN` through a secure
environment injection mechanism, using only your own GitHub credential with
Copilot access.
Never put its value in shell history, command arguments, a committed file, or logs.
The command requires this explicit credential and calls only `listModels()`;
it never falls back to persisted Copilot/keychain credentials, `gh` login, or
ambient `GH_TOKEN`, `GITHUB_TOKEN`, or `COPILOT_GITHUB_TOKEN`.
SDK empty mode and the isolated directory hide persisted credentials, so a
desktop Copilot login alone is not sufficient.
It creates an isolated temporary SDK directory, uses error-only logging, prints
only `exactModel`, `entitled`, and `matchCount`, and deletes the directory only
after a confirmed graceful SDK shutdown.
The probe has a 30-second deadline and allows five seconds for graceful shutdown
before requesting a forced stop.
If SDK startup or the runtime handshake is still pending at the deadline, the
probe forces a stop. Because the SDK may spawn its runtime after that first stop,
the probe repeats forced stops for up to five more seconds until startup settles.
This also kills a runtime spawned after the deadline whose handshake never completes.
If startup still has not settled, the command sends a final synchronous forced
stop and exits immediately, so no runtime can be spawned after the command ends.
If termination cannot be confirmed, the command fails without a model result and
retains its `penge-copilot-entitlement-*` temporary directory.
On POSIX, `SIGINT` and `SIGTERM` interrupt the probe and trigger the same bounded
cleanup without printing a model result; the exit status is `130` or `143` for
the first signal received.
Further signals do not interrupt cleanup.
`SIGKILL` or abrupt host failure cannot be handled, so check for any surviving
runtime before removing retained storage.
After confirming that the corresponding runtime is no longer running, remove
that isolated directory securely; never inspect or publish its contents.
It never prints a token, login, prompt, or financial data.
Exit status `2` means the exact ID is missing, duplicated, or blocked by policy.
The SDK may omit policy metadata; when present, its state must be `enabled`.

The historical 2026-10-04 result was:

```json
{ "exactModel": "hydrafusion", "entitled": false, "matchCount": 0 }
```

That historical diagnostic used implicit authentication and does not establish
which account supplied it.
It is not verified entitlement evidence; rerun with the explicit credential
before drawing any current account-specific conclusion.

Do not create an entitlement record from documentation, a different account,
a display name, or a similar model ID.
Never ask for or use another household member's credentials to run this check.
This CLI check uses the client identity and cannot prove entitlement for a
different session actor.
SDK 1.0.16 also exposes experimental `session.rpc.model.list()` for the
session's own authentication context; its results are untyped JSON and must
be validated before they are used for an actor-scoped decision.
Successful session creation alone is not evidence that the model can execute.

## MCP child credentials and attribution

The proof accepts exactly one of `PENGE_DB_URL` or `PENGE_DB_URL_FILE`.
The latter passes only the secret-file path to MCP; MCP owns secure file
opening, ownership/mode checks, size bounds, and URL validation.
It is not read or logged by the feasibility harness.
No ambient authentication variables are accepted in the MCP environment.

The trusted caller supplies the current actor ID and session ID as canonical
`actor_<ULID>` and `session_<ULID>` pseudonyms.
The proof uses the session ID for the SDK session and injects
`PENGE_MCP_ACTOR_ID` / `PENGE_MCP_SESSION_ID` into the child environment.
Explicit child attribution, if supplied, must match those trusted values;
malformed or cross-actor/cross-session values are rejected.
Browsers must not choose these IDs or overwrite audit attribution.

## Production enablement checklist

Issue #346 may enable a linked actor only after all checks pass:

1. The actor uses that person's own GitHub account, Copilot entitlement, OAuth
   credential, and quota.
   SDK storage is derived from the actor ID below a trusted absolute root.
2. The actor-scoped model listing contains exactly one `hydrafusion` entry.
   If policy metadata is present, its state must be `enabled`.
3. The successful check is persisted for exactly that actor, normalized linked
   GitHub login, and `hydrafusion` model ID.
   A record for another actor or linked identity is rejected.
4. SDK and MCP child environments exclude ambient authentication variables.
5. The owner accepts the proposed ADR-0005 amendment from #390 through
   repository review, or the transaction search and detail tools are removed
   from the model-facing allowlist and an updated contract is verified against
   the aggregate-only boundary.
   Merging the proposal is not owner acceptance.
6. Real stdio `tools/list` evidence matches the selected, policy-compliant
   contract; registration alone does not authorize model exposure.
7. `PENGE_CHAT_MODEL=hydrafusion` and
   `PENGE_CHAT_ENABLE_PRODUCTION=1` are set.
   The deployment switch never substitutes for the actor-scoped record.
8. `PENGE_CHAT_FALLBACK_MODEL` is unset.
9. The runtime uses `mode: "empty"`, denies built-in/custom tools and every
   non-MCP permission request, and starts only the local stdio Penge MCP server.
   It approves once only for a read-only request matching the exact `penge`
   server and configured tool allowlist.
10. Network tests prove no MCP, Copilot runtime, database, or raw tool port is
   reachable.
11. Cancellation, timeout, process cleanup, ephemeral transcripts, redacted
   audits, token encryption/rotation, backup, and rollback tests pass.

If any check fails, keep chat disabled and return a typed unavailable or
disabled error.
