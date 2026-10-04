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

  it("serializes concurrent refreshes and persists one rotated envelope", async () => {
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

    const provider = new UserTokenService(config, store, fetcher).providerFor(actorId);
    const request = {
      host: "github.com",
      sessionId: "session",
      reason: "refresh" as const,
    };
    const [firstToken, secondToken] = await Promise.all([provider(request), provider(request)]);
    expect(firstToken).toMatchObject({ kind: "token", accessToken: "rotated-access" });
    expect(secondToken).toMatchObject({ kind: "token", accessToken: "rotated-access" });
    expect(fetcher).toHaveBeenCalledTimes(3);
    expect(JSON.stringify(store.links.get(actorId)?.tokenEnvelope)).not.toBe(before);
  });

  it("does not let an overlapping refresh overwrite a newly linked account", async () => {
    const config = syntheticConfig();
    const store = new MemoryChatStore();
    const actorId = "actor_0123456789abcdef0123456789abcdef";
    const initialResponses = [
      new Response(
        JSON.stringify({
          access_token: "old-access",
          refresh_token: "old-refresh",
          expires_in: 10,
          refresh_token_expires_in: 100_000,
          scope: "",
          token_type: "bearer",
        }),
        { headers: { "content-type": "application/json" } },
      ),
      new Response(JSON.stringify({ id: 42, login: "old-user" }), {
        headers: { "content-type": "application/json" },
      }),
    ];
    const initialFlow = new GitHubOAuthFlow(
      config,
      store,
      vi.fn(async () => initialResponses.shift()!) as typeof fetch,
    );
    const initialUrl = new URL(await initialFlow.begin(actorId));
    await initialFlow.complete(actorId, initialUrl.searchParams.get("state")!, "old-code");

    let releaseRefresh = (_response: Response): void => undefined;
    const refreshResponse = new Promise<Response>((resolve) => {
      releaseRefresh = resolve;
    });
    const refreshFetcher = vi.fn(async () => refreshResponse) as typeof fetch;
    const provider = new UserTokenService(config, store, refreshFetcher).providerFor(actorId);
    const refresh = provider({
      host: "github.com",
      sessionId: "refresh-session",
      reason: "refresh",
    });
    await vi.waitFor(() => expect(refreshFetcher).toHaveBeenCalledTimes(1));

    const relinkResponses = [
      new Response(
        JSON.stringify({
          access_token: "new-access",
          refresh_token: "new-refresh",
          expires_in: 28_800,
          refresh_token_expires_in: 100_000,
          scope: "",
          token_type: "bearer",
        }),
        { headers: { "content-type": "application/json" } },
      ),
      new Response(JSON.stringify({ id: 84, login: "new-user" }), {
        headers: { "content-type": "application/json" },
      }),
    ];
    const relinkFetcher = vi.fn(async () => relinkResponses.shift()!) as typeof fetch;
    const relinkFlow = new GitHubOAuthFlow(config, store, relinkFetcher);
    const relinkUrl = new URL(await relinkFlow.begin(actorId));
    const relink = relinkFlow.complete(actorId, relinkUrl.searchParams.get("state")!, "new-code");
    await vi.waitFor(() => expect(relinkFetcher).toHaveBeenCalledTimes(2));

    releaseRefresh(
      new Response(
        JSON.stringify({
          access_token: "rotated-old-access",
          refresh_token: "rotated-old-refresh",
          expires_in: 28_800,
          scope: "",
          token_type: "bearer",
        }),
        { headers: { "content-type": "application/json" } },
      ),
    );
    await expect(refresh).resolves.toMatchObject({ accessToken: "rotated-old-access" });
    await expect(relink).resolves.toBe("new-user");
    await expect(relinkFlow.status(actorId)).resolves.toEqual({
      state: "linked",
      login: "new-user",
    });
    await expect(
      provider({ host: "github.com", sessionId: "next", reason: "refresh" }),
    ).resolves.toMatchObject({ accessToken: "new-access" });
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
