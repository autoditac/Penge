import { describe, expect, it, vi } from "vitest";

import {
  bindTrustedIdentity,
  decryptOAuthState,
  decryptTokenBundle,
  encryptOAuthState,
  encryptTokenBundle,
  exchangeGitHubCode,
  generateOAuthState,
  refreshGitHubToken,
  type TokenBundle,
} from "../src/identity.js";

const bundle: TokenBundle = {
  accessToken: "synthetic-access",
  refreshToken: "synthetic-refresh",
  expiresAt: "2026-10-04T12:00:00.000Z",
  refreshTokenExpiresAt: "2027-01-01T00:00:00.000Z",
  scope: ["read:user"],
  tokenType: "bearer",
  githubUserId: 42,
  githubLogin: "synthetic-user",
};

describe("identity and OAuth", () => {
  it("binds only immutable proxy subjects accompanied by the shared proxy secret", () => {
    const headers = {
      "x-penge-proxy-secret": "p".repeat(32),
      "x-penge-auth-issuer": "https://accounts.google.com",
      "x-penge-auth-subject": "google-subject-123",
    };
    const identity = bindTrustedIdentity(
      headers,
      "https://accounts.google.com",
      "i".repeat(32),
      "p".repeat(32),
    );
    expect(identity.actorId).toMatch(/^actor_[a-f0-9]{32}$/);
    expect(JSON.stringify(identity)).not.toContain("google-subject-123");
    expect(() =>
      bindTrustedIdentity(
        { ...headers, "x-penge-proxy-secret": "x".repeat(32) },
        "https://accounts.google.com",
        "i".repeat(32),
        "p".repeat(32),
      ),
    ).toThrow(/trusted reverse proxy/);
  });

  it("encrypts versioned token and PKCE state envelopes and decrypts old rotation keys", () => {
    const oldKey = Buffer.alloc(32, 1);
    const state = generateOAuthState(
      "actor_0123456789abcdef0123456789abcdef",
      "https://penge.example.test/cb",
    );
    const tokenEnvelope = encryptTokenBundle(bundle, oldKey, "old");
    const stateEnvelope = encryptOAuthState(state, oldKey, "old");
    const serialized = JSON.stringify({ tokenEnvelope, stateEnvelope });
    expect(serialized).not.toContain(bundle.accessToken);
    expect(serialized).not.toContain(state.codeVerifier);
    const keyring = new Map([
      ["old", oldKey],
      ["current", Buffer.alloc(32, 2)],
    ]);
    expect(decryptTokenBundle(tokenEnvelope, keyring)).toEqual(bundle);
    expect(decryptOAuthState(stateEnvelope, keyring)).toEqual(state);
  });

  it("sends PKCE verifier on exchange and rotates refresh credentials", async () => {
    const responses = [
      new Response(
        JSON.stringify({
          access_token: "access-1",
          refresh_token: "refresh-1",
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
    let firstRequest: RequestInit | undefined;
    const fetcher: typeof fetch = async (_input, init) => {
      firstRequest ??= init;
      return responses.shift()!;
    };
    const state = generateOAuthState(
      "actor_0123456789abcdef0123456789abcdef",
      "https://penge.example.test/oauth/github/callback",
    );
    const config = {
      clientId: "client",
      clientSecret: "secret",
      authorizeUrl: "https://github.com/login/oauth/authorize",
      tokenUrl: "https://github.com/login/oauth/access_token",
      apiUrl: "https://api.github.com",
    };
    const exchanged = await exchangeGitHubCode(
      config,
      "code",
      state,
      fetcher,
      Date.parse("2026-10-04T10:00:00.000Z"),
    );
    const exchangeBody = JSON.parse(String(firstRequest?.body)) as Record<string, unknown>;
    expect(exchangeBody.code_verifier).toBe(state.codeVerifier);
    expect(exchanged.githubUserId).toBe(42);

    const refreshFetcher = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            access_token: "access-2",
            refresh_token: "refresh-2",
            expires_in: 28_800,
            scope: "read:user",
            token_type: "bearer",
          }),
          { headers: { "content-type": "application/json" } },
        ),
    );
    const refreshed = await refreshGitHubToken(
      config,
      exchanged,
      refreshFetcher as typeof fetch,
      Date.parse("2026-10-04T11:00:00.000Z"),
    );
    expect(refreshed.accessToken).toBe("access-2");
    expect(refreshed.refreshToken).toBe("refresh-2");
  });
});
