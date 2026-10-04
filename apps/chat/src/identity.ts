import { createCipheriv, createDecipheriv, createHash, randomBytes } from "node:crypto";
import { z } from "zod/v3";

export const OAuthStateSchema = z.object({
  state: z.string().min(16),
  codeVerifier: z.string().min(32),
  codeChallenge: z.string().min(32),
  redirectUri: z.string().url(),
  provider: z.enum(["google-oauth2-proxy", "github-app"]),
  userId: z.string().min(1),
});

export type GenerateOAuthStateInput = {
  state?: string;
  codeVerifier?: string;
  codeChallenge?: string;
  redirectUri: string;
  provider: "google-oauth2-proxy" | "github-app";
  userId: string;
};

export const TokenBundleSchema = z.object({
  accessToken: z.string().min(1),
  refreshToken: z.string().nullable().default(null),
  expiresAt: z.string().datetime(),
  scope: z.array(z.string()).default([]),
});

export type OAuthState = z.infer<typeof OAuthStateSchema>;
export type TokenBundle = z.infer<typeof TokenBundleSchema>;

export function generatePkce(): { codeVerifier: string; codeChallenge: string } {
  const codeVerifier = randomBytes(32).toString("base64url");
  const digest = createHash("sha256").update(codeVerifier).digest();
  const codeChallenge = digest.toString("base64url");
  return { codeVerifier, codeChallenge };
}

export function generateOAuthState(input: GenerateOAuthStateInput): OAuthState {
  const { codeVerifier, codeChallenge } = generatePkce();
  return OAuthStateSchema.parse({
    ...input,
    state: input.state ?? randomBytes(24).toString("base64url"),
    codeVerifier: input.codeVerifier ?? codeVerifier,
    codeChallenge: input.codeChallenge ?? codeChallenge,
  });
}

export function buildGitHubAuthorisationUrl(
  clientId: string,
  redirectUri: string,
  state: string,
  codeChallenge: string,
): string {
  const params = new URLSearchParams({
    client_id: clientId,
    redirect_uri: redirectUri,
    state,
    response_type: "code",
    code_challenge: codeChallenge,
    code_challenge_method: "S256",
    scope: "read:user user:email",
  });
  return `https://github.com/login/oauth/authorize?${params.toString()}`;
}

export function bindIdentity(
  googleSubject: string,
  githubLogin: string,
): { actorId: string; subjectId: string } {
  const seed = `${googleSubject}:${githubLogin}`;
  const actorId = createHash("sha256").update(seed).digest("hex").slice(0, 24);
  return { actorId, subjectId: `${googleSubject}:${githubLogin}` };
}

export function encryptTokenBundle(bundle: TokenBundle, encryptionKey: string): string {
  const key = createHash("sha256").update(encryptionKey).digest();
  const iv = randomBytes(12);
  const payload = Buffer.from(JSON.stringify(bundle), "utf8");
  const cipher = createCipheriv("aes-256-gcm", key, iv);
  const encrypted = Buffer.concat([cipher.update(payload), cipher.final()]);
  const tag = cipher.getAuthTag();
  const versioned = Buffer.concat([Buffer.from("v1:"), iv, tag, encrypted]);
  return versioned.toString("base64url");
}

export function decryptTokenBundle(serialized: string, encryptionKey: string): TokenBundle {
  const decoded = Buffer.from(serialized, "base64url");
  if (decoded.subarray(0, 3).toString("utf8") !== "v1:") {
    throw new Error("unsupported encrypted token version");
  }
  const iv = decoded.subarray(3, 15);
  const tag = decoded.subarray(15, 31);
  const encrypted = decoded.subarray(31);
  const key = createHash("sha256").update(encryptionKey).digest();
  const decipher = createDecipheriv("aes-256-gcm", key, iv);
  decipher.setAuthTag(tag);
  const cleartext = Buffer.concat([decipher.update(encrypted), decipher.final()]).toString("utf8");
  return TokenBundleSchema.parse(JSON.parse(cleartext) as unknown);
}
