import { describe, expect, it, vi } from "vitest";

import { GitHubOAuthFlow, UserTokenService } from "../src/oauth.js";
import { MemoryChatStore, syntheticConfig } from "./helpers.js";

describe("GitHub OAuth persistence", () => {
  it("stores only hashed lookup state, consumes it once, and links the GitHub user", async () => {
    const store = new MemoryChatStore();
    const responses = [
      new Response(
        JSON.stringify({
          access_token: "synthetic-access",
          refresh_token: "synthetic-refresh",
          expires_in: 28_800,
          refresh_token_expires_in: 100_000,
          scope: "read:user",
          token_type: "bearer",
        }),
        { headers: { "content-type": "application/json" } },
      ),
      new Response(JSON.stringify({ id: 42, login: "synthetic-user" }), {
        headers: { "content-type": "application/json" },
      }),
    ];
    const flow = new GitHubOAuthFlow(
      syntheticConfig(),
      store,
      vi.fn(async () => responses.shift()!) as typeof fetch,
    );
    const actorId = "actor_0123456789abcdef0123456789abcdef";
    const authorizationUrl = new URL(await flow.begin(actorId));
    const state = authorizationUrl.searchParams.get("state")!;
    expect([...store.states.keys()]).not.toContain(state);
    expect(JSON.stringify([...store.states.values()])).not.toContain("codeVerifier");

    await expect(flow.complete(actorId, state, "code")).resolves.toBe("synthetic-user");
    expect(store.links.get(actorId)).toMatchObject({
      githubUserId: 42,
      githubLogin: "synthetic-user",
    });
    await expect(flow.complete(actorId, state, "code")).rejects.toThrow(/already consumed/);
  });

  it("refreshes expiring user tokens and persists the rotated envelope", async () => {
    const config = syntheticConfig();
    const store = new MemoryChatStore();
    const actorId = "actor_0123456789abcdef0123456789abcdef";
    const responses = [
      new Response(
        JSON.stringify({
          access_token: "short-access",
          refresh_token: "refresh-1",
          expires_in: 10,
          refresh_token_expires_in: 100_000,
          scope: "read:user",
          token_type: "bearer",
        }),
        { headers: { "content-type": "application/json" } },
      ),
      new Response(JSON.stringify({ id: 42, login: "synthetic-user" }), {
        headers: { "content-type": "application/json" },
      }),
      new Response(
        JSON.stringify({
          access_token: "rotated-access",
          refresh_token: "refresh-2",
          expires_in: 28_800,
          scope: "read:user",
          token_type: "bearer",
        }),
        { headers: { "content-type": "application/json" } },
      ),
    ];
    const fetcher = vi.fn(async () => responses.shift()!) as typeof fetch;
    const flow = new GitHubOAuthFlow(config, store, fetcher);
    const url = new URL(await flow.begin(actorId));
    await flow.complete(actorId, url.searchParams.get("state")!, "code");
    const before = JSON.stringify(store.links.get(actorId)?.tokenEnvelope);

    const token = await new UserTokenService(config, store, fetcher).providerFor(actorId)({
      host: "github.com",
      sessionId: "session",
      reason: "refresh",
    });
    expect(token).toMatchObject({ kind: "token", accessToken: "rotated-access" });
    expect(JSON.stringify(store.links.get(actorId)?.tokenEnvelope)).not.toBe(before);
  });
});
