import {
  createCipheriv,
  createDecipheriv,
  createHash,
  createHmac,
  randomBytes,
  timingSafeEqual,
} from "node:crypto";
import type { IncomingHttpHeaders } from "node:http";

import { z } from "zod/v3";

import { AuthenticationError } from "./errors.js";

export const TrustedIdentitySchema = z
  .object({
    actorId: z.string().regex(/^actor_[a-f0-9]{32}$/),
    issuer: z.string().min(1),
  })
  .strict();

export const OAuthStateSchema = z
  .object({
    state: z.string().min(32),
    actorId: z.string().regex(/^actor_[a-f0-9]{32}$/),
    codeVerifier: z.string().min(43).max(128),
    codeChallenge: z.string().min(43).max(128),
    redirectUri: z.string().url(),
    expiresAt: z.string().datetime(),
  })
  .strict();

export const TokenBundleSchema = z
  .object({
    accessToken: z.string().min(1),
    refreshToken: z.string().min(1).nullable(),
    expiresAt: z.string().datetime().nullable(),
    refreshTokenExpiresAt: z.string().datetime().nullable(),
    scope: z.array(z.string()),
    tokenType: z.literal("bearer"),
    githubUserId: z.number().int().positive(),
    githubLogin: z.string().min(1),
  })
  .strict();

const EncryptedEnvelopeSchema = z
  .object({
    version: z.literal(1),
    keyId: z.string().min(1),
    algorithm: z.literal("A256GCM"),
    purpose: z.enum(["token", "oauth-state"]),
    iv: z.string().min(1),
    tag: z.string().min(1),
    ciphertext: z.string().min(1),
  })
  .strict();

const GitHubTokenResponseSchema = z
  .object({
    access_token: z.string().min(1),
    refresh_token: z.string().min(1).optional(),
    expires_in: z.number().int().positive().optional(),
    refresh_token_expires_in: z.number().int().positive().optional(),
    scope: z.string().default(""),
    token_type: z.string().transform((value) => value.toLowerCase()),
    error: z.string().optional(),
    error_description: z.string().optional(),
  })
  .passthrough();

const GitHubUserSchema = z
  .object({
    id: z.number().int().positive(),
    login: z.string().min(1),
  })
  .passthrough();

export type TrustedIdentity = z.infer<typeof TrustedIdentitySchema>;
export type OAuthState = z.infer<typeof OAuthStateSchema>;
export type TokenBundle = z.infer<typeof TokenBundleSchema>;
export type EncryptedEnvelope = z.infer<typeof EncryptedEnvelopeSchema>;

export interface GitHubOAuthConfig {
  clientId: string;
  clientSecret: string;
  authorizeUrl: string;
  tokenUrl: string;
  apiUrl: string;
}

function singleHeader(headers: IncomingHttpHeaders, name: string): string {
  const value = headers[name];
  if (typeof value !== "string" || value.trim() === "" || value.includes(",")) {
    throw new AuthenticationError(`trusted proxy header ${name} is missing or ambiguous`);
  }
  return value.trim();
}

export function bindTrustedIdentity(
  headers: IncomingHttpHeaders,
  expectedIssuer: string,
  pepper: string,
  expectedProxySecret: string,
): TrustedIdentity {
  const proxySecret = singleHeader(headers, "x-penge-proxy-secret");
  const suppliedSecret = Buffer.from(proxySecret);
  const configuredSecret = Buffer.from(expectedProxySecret);
  if (
    suppliedSecret.length !== configuredSecret.length ||
    !timingSafeEqual(suppliedSecret, configuredSecret)
  ) {
    throw new AuthenticationError("request did not pass through the trusted reverse proxy");
  }
  const issuer = singleHeader(headers, "x-penge-auth-issuer");
  const subject = singleHeader(headers, "x-penge-auth-subject");
  const actual = Buffer.from(issuer);
  const expected = Buffer.from(expectedIssuer);
  if (actual.length !== expected.length || !timingSafeEqual(actual, expected)) {
    throw new AuthenticationError("request was not issued by the configured oauth2-proxy");
  }
  const digest = createHmac("sha256", pepper).update(`${issuer}\0${subject}`).digest("hex");
  return TrustedIdentitySchema.parse({ actorId: `actor_${digest.slice(0, 32)}`, issuer });
}

export function hashOAuthState(state: string, pepper: string): string {
  return createHmac("sha256", pepper).update(`oauth-state\0${state}`).digest("hex");
}

export function generatePkce(): { codeVerifier: string; codeChallenge: string } {
  const codeVerifier = randomBytes(48).toString("base64url");
  const codeChallenge = createHash("sha256").update(codeVerifier).digest("base64url");
  return { codeVerifier, codeChallenge };
}

export function generateOAuthState(
  actorId: string,
  redirectUri: string,
  ttlMs = 10 * 60_000,
  now = Date.now(),
): OAuthState {
  const { codeVerifier, codeChallenge } = generatePkce();
  return OAuthStateSchema.parse({
    state: randomBytes(32).toString("base64url"),
    actorId,
    codeVerifier,
    codeChallenge,
    redirectUri,
    expiresAt: new Date(now + ttlMs).toISOString(),
  });
}

export function buildGitHubAuthorisationUrl(
  config: Pick<GitHubOAuthConfig, "authorizeUrl" | "clientId">,
  oauthState: OAuthState,
): string {
  const url = new URL(config.authorizeUrl);
  url.search = new URLSearchParams({
    client_id: config.clientId,
    redirect_uri: oauthState.redirectUri,
    state: oauthState.state,
    code_challenge: oauthState.codeChallenge,
    code_challenge_method: "S256",
  }).toString();
  return url.toString();
}

function futureIso(seconds: number | undefined, now: number): string | null {
  return seconds === undefined ? null : new Date(now + seconds * 1000).toISOString();
}

async function parseGitHubResponse(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    throw new AuthenticationError("GitHub OAuth returned a non-JSON response");
  }
  const body: unknown = await response.json();
  if (!response.ok) {
    throw new AuthenticationError(`GitHub OAuth request failed with status ${response.status}`);
  }
  return body;
}

export async function exchangeGitHubCode(
  config: GitHubOAuthConfig,
  code: string,
  oauthState: OAuthState,
  fetcher: typeof fetch = fetch,
  now = Date.now(),
): Promise<TokenBundle> {
  const response = await fetcher(config.tokenUrl, {
    method: "POST",
    headers: { accept: "application/json", "content-type": "application/json" },
    body: JSON.stringify({
      client_id: config.clientId,
      client_secret: config.clientSecret,
      code,
      redirect_uri: oauthState.redirectUri,
      code_verifier: oauthState.codeVerifier,
    }),
    signal: AbortSignal.timeout(15_000),
  });
  const token = GitHubTokenResponseSchema.parse(await parseGitHubResponse(response));
  if (token.error !== undefined || token.token_type !== "bearer") {
    throw new AuthenticationError(token.error_description ?? token.error ?? "invalid token type");
  }

  const userResponse = await fetcher(`${config.apiUrl.replace(/\/$/, "")}/user`, {
    headers: {
      accept: "application/vnd.github+json",
      authorization: `Bearer ${token.access_token}`,
      "x-github-api-version": "2022-11-28",
    },
    signal: AbortSignal.timeout(15_000),
  });
  const user = GitHubUserSchema.parse(await parseGitHubResponse(userResponse));
  return TokenBundleSchema.parse({
    accessToken: token.access_token,
    refreshToken: token.refresh_token ?? null,
    expiresAt: futureIso(token.expires_in, now),
    refreshTokenExpiresAt: futureIso(token.refresh_token_expires_in, now),
    scope: token.scope.split(/[,\s]+/).filter(Boolean),
    tokenType: "bearer",
    githubUserId: user.id,
    githubLogin: user.login,
  });
}

export async function refreshGitHubToken(
  config: GitHubOAuthConfig,
  current: TokenBundle,
  fetcher: typeof fetch = fetch,
  now = Date.now(),
): Promise<TokenBundle> {
  if (current.refreshToken === null) {
    throw new AuthenticationError("GitHub token is expired and has no refresh token");
  }
  const response = await fetcher(config.tokenUrl, {
    method: "POST",
    headers: { accept: "application/json", "content-type": "application/json" },
    body: JSON.stringify({
      client_id: config.clientId,
      client_secret: config.clientSecret,
      grant_type: "refresh_token",
      refresh_token: current.refreshToken,
    }),
    signal: AbortSignal.timeout(15_000),
  });
  const token = GitHubTokenResponseSchema.parse(await parseGitHubResponse(response));
  if (token.error !== undefined || token.token_type !== "bearer") {
    throw new AuthenticationError(token.error_description ?? token.error ?? "invalid token type");
  }
  return TokenBundleSchema.parse({
    ...current,
    accessToken: token.access_token,
    refreshToken: token.refresh_token ?? current.refreshToken,
    expiresAt: futureIso(token.expires_in, now),
    refreshTokenExpiresAt:
      futureIso(token.refresh_token_expires_in, now) ?? current.refreshTokenExpiresAt,
    scope: token.scope.split(/[,\s]+/).filter(Boolean),
  });
}

function encryptPayload(
  payload: unknown,
  encryptionKey: Buffer,
  keyId: string,
  purpose: "token" | "oauth-state",
): EncryptedEnvelope {
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", encryptionKey, iv);
  cipher.setAAD(Buffer.from(`penge-chat:${purpose}:v1:${keyId}`));
  const ciphertext = Buffer.concat([
    cipher.update(JSON.stringify(payload), "utf8"),
    cipher.final(),
  ]);
  return EncryptedEnvelopeSchema.parse({
    version: 1,
    keyId,
    algorithm: "A256GCM",
    purpose,
    iv: iv.toString("base64url"),
    tag: cipher.getAuthTag().toString("base64url"),
    ciphertext: ciphertext.toString("base64url"),
  });
}

function decryptPayload(
  envelopeInput: unknown,
  keyring: ReadonlyMap<string, Buffer>,
  purpose: "token" | "oauth-state",
): unknown {
  const envelope = EncryptedEnvelopeSchema.parse(envelopeInput);
  if (envelope.purpose !== purpose) {
    throw new AuthenticationError(`encrypted envelope is not a ${purpose} envelope`);
  }
  const key = keyring.get(envelope.keyId);
  if (key === undefined) {
    throw new AuthenticationError(`token encryption key ${envelope.keyId} is unavailable`);
  }
  const decipher = createDecipheriv("aes-256-gcm", key, Buffer.from(envelope.iv, "base64url"));
  decipher.setAAD(Buffer.from(`penge-chat:${purpose}:v1:${envelope.keyId}`));
  decipher.setAuthTag(Buffer.from(envelope.tag, "base64url"));
  const cleartext = Buffer.concat([
    decipher.update(Buffer.from(envelope.ciphertext, "base64url")),
    decipher.final(),
  ]).toString("utf8");
  return JSON.parse(cleartext) as unknown;
}

export function encryptTokenBundle(
  bundle: TokenBundle,
  encryptionKey: Buffer,
  keyId: string,
): EncryptedEnvelope {
  return encryptPayload(TokenBundleSchema.parse(bundle), encryptionKey, keyId, "token");
}

export function decryptTokenBundle(
  envelopeInput: unknown,
  keyring: ReadonlyMap<string, Buffer>,
): TokenBundle {
  return TokenBundleSchema.parse(decryptPayload(envelopeInput, keyring, "token"));
}

export function encryptOAuthState(
  state: OAuthState,
  encryptionKey: Buffer,
  keyId: string,
): EncryptedEnvelope {
  return encryptPayload(OAuthStateSchema.parse(state), encryptionKey, keyId, "oauth-state");
}

export function decryptOAuthState(
  envelopeInput: unknown,
  keyring: ReadonlyMap<string, Buffer>,
): OAuthState {
  return OAuthStateSchema.parse(decryptPayload(envelopeInput, keyring, "oauth-state"));
}
