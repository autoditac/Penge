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
    expect(authorizationUrl.searchParams.has("scope")).toBe(false);
    expect([...store.states.keys()]).not.toContain(state);
    expect(JSON.stringify([...store.states.values()])).not.toContain("codeVerifier");

    await expect(flow.complete(actorId, state, "code")).resolves.toBe("synthetic-user");
    expect(store.links.get(actorId)).toMatchObject({
      githubUserId: 42,
      githubLogin: "synthetic-user",
    });

    await expect(flow.status(actorId)).resolves.toEqual({
      state: "linked",
      login: "synthetic-user",
    });
    await expect(flow.complete(actorId, state, "code")).rejects.toThrow(/already consumed/);
    await flow.unlink(actorId);
    await expect(flow.status(actorId)).resolves.toEqual({
      state: "not-linked",
      login: null,
    });
  });

  it("preserves an external API prefix and caps pending state per actor", async () => {
    const store = new MemoryChatStore();
    const flow = new GitHubOAuthFlow(
      syntheticConfig({
        publicApiBase: "https://penge.example.test/ask/api/",
        publicAppOrigin: "https://penge.example.test",
      }),
      store,
    );
    const actorId = "actor_0123456789abcdef0123456789abcdef";
    const first = new URL(await flow.begin(actorId));
    const second = new URL(await flow.begin(actorId));
    expect(first.searchParams.get("redirect_uri")).toBe(
      "https://penge.example.test/ask/api/oauth/github/callback",
    );
    expect(second.searchParams.get("redirect_uri")).toBe(
      "https://penge.example.test/ask/api/oauth/github/callback",
    );
    expect(store.states.size).toBe(1);
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

  it("rejects mismatched link metadata and duplicate GitHub identities across actors", async () => {
    const config = syntheticConfig();
    const store = new MemoryChatStore();
    const tokenResponse = () =>
      new Response(
        JSON.stringify({
          access_token: "synthetic-access",
          refresh_token: "synthetic-refresh",
          expires_in: 28_800,
          refresh_token_expires_in: 100_000,
          scope: "",
          token_type: "bearer",
        }),
        { headers: { "content-type": "application/json" } },
      );
    const userResponse = () =>
      new Response(JSON.stringify({ id: 42, login: "synthetic-user" }), {
        headers: { "content-type": "application/json" },
      });
    const responses = [tokenResponse(), userResponse(), tokenResponse(), userResponse()];
    const fetcher = vi.fn(async () => responses.shift()!) as typeof fetch;
    const flow = new GitHubOAuthFlow(config, store, fetcher);
    const actorA = "actor_0123456789abcdef0123456789abcdef";
    const actorB = "actor_fedcba9876543210fedcba9876543210";
    const first = new URL(await flow.begin(actorA));
    await flow.complete(actorA, first.searchParams.get("state")!, "code-a");
    const second = new URL(await flow.begin(actorB));
    await expect(
      flow.complete(actorB, second.searchParams.get("state")!, "code-b"),
    ).rejects.toThrow(/unique github_user_id/);

    const link = store.links.get(actorA);
    if (link === undefined) throw new Error("synthetic link missing");
    store.links.set(actorA, { ...link, githubLogin: "different-user" });
    const tokens = new UserTokenService(config, store, fetcher);
    await expect(
      tokens.providerFor(actorA)({
        host: "github.com",
        sessionId: "session",
        reason: "initial",
      }),
    ).rejects.toThrow(/does not match token envelope/);
    await expect(flow.status(actorA)).rejects.toThrow(/does not match token envelope/);
  });

  it("reports an unusable short-lived token without refresh as expired", async () => {
    const store = new MemoryChatStore();
    const responses = [
      new Response(
        JSON.stringify({
          access_token: "short-access",
          expires_in: 10,
          scope: "",
          token_type: "bearer",
        }),
        { headers: { "content-type": "application/json" } },
      ),
      new Response(JSON.stringify({ id: 99, login: "short-lived-user" }), {
        headers: { "content-type": "application/json" },
      }),
    ];
    const flow = new GitHubOAuthFlow(
      syntheticConfig(),
      store,
      vi.fn(async () => responses.shift()!) as typeof fetch,
    );
    const actorId = "actor_0123456789abcdef0123456789abcdef";
    const url = new URL(await flow.begin(actorId));
    await flow.complete(actorId, url.searchParams.get("state")!, "code");
    await expect(flow.status(actorId)).resolves.toEqual({
      state: "expired",
      login: "short-lived-user",
    });
  });
});
