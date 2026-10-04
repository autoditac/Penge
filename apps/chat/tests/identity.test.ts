import { describe, expect, it } from "vitest";

import {
  bindIdentity,
  buildGitHubAuthorisationUrl,
  decryptTokenBundle,
  encryptTokenBundle,
  generateOAuthState,
  generatePkce,
} from "../src/identity.js";

describe("oauth identity helpers", () => {
  it("derives a stable actor identity from Google and GitHub identity", () => {
    const identity = bindIdentity("google-user-123", "octocat");
    expect(identity.actorId).toMatch(/^[a-f0-9]{24}$/);
    expect(identity.subjectId).toBe("google-user-123:octocat");
  });

  it("generates PKCE and authorisation URLs with exact state and challenge", () => {
    const { codeVerifier, codeChallenge } = generatePkce();
    const state = generateOAuthState({
      state: "state-1234567890",
      codeVerifier,
      codeChallenge,
      redirectUri: "http://127.0.0.1:3000/oauth/callback",
      provider: "github-app",
      userId: "user-123",
    });

    const url = buildGitHubAuthorisationUrl(
      "client-id",
      state.redirectUri,
      state.state,
      state.codeChallenge,
    );
    expect(url).toContain("client_id=client-id");
    expect(url).toContain(`state=${state.state}`);
    expect(url).toContain(`code_challenge=${state.codeChallenge}`);
    expect(codeVerifier.length).toBeGreaterThanOrEqual(32);
    expect(codeChallenge.length).toBeGreaterThanOrEqual(32);
  });

  it("round-trips encrypted token metadata without exposing secrets", () => {
    const bundle = {
      accessToken: "gho_secret",
      refreshToken: "refresh-secret",
      expiresAt: new Date(Date.now() + 60_000).toISOString(),
      scope: ["read:user", "user:email"],
    };
    const serialized = encryptTokenBundle(bundle, "12345678901234567890123456789012");
    const decrypted = decryptTokenBundle(serialized, "12345678901234567890123456789012");
    expect(decrypted.accessToken).toBe(bundle.accessToken);
    expect(decrypted.refreshToken).toBe(bundle.refreshToken);
    expect(decrypted.scope).toEqual(bundle.scope);
  });
});
