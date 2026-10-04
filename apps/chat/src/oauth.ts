import type { GitHubTokenProvider } from "@github/copilot-sdk";

import type { ChatConfig } from "./config.js";
import { AuthenticationError, ChatConfigError } from "./errors.js";
import {
  buildGitHubAuthorisationUrl,
  decryptOAuthState,
  decryptTokenBundle,
  encryptOAuthState,
  encryptTokenBundle,
  exchangeGitHubCode,
  generateOAuthState,
  hashOAuthState,
  refreshGitHubToken,
  type GitHubOAuthConfig,
  type TokenBundle,
} from "./identity.js";
import type { ChatStore } from "./store.js";

const SDK_MINIMUM_LIFETIME_SECONDS = 60 * 60;
const NON_EXPIRING_TOKEN_LIFETIME_SECONDS = 8 * 60 * 60;

function remainingSeconds(bundle: TokenBundle, now: number): number {
  if (bundle.expiresAt === null) {
    return NON_EXPIRING_TOKEN_LIFETIME_SECONDS;
  }
  return Math.max(0, Math.floor((new Date(bundle.expiresAt).getTime() - now) / 1000));
}

export class UserTokenService {
  private readonly oauthConfig: GitHubOAuthConfig;
  private readonly keyring: ReadonlyMap<string, Buffer>;

  constructor(
    private readonly config: ChatConfig,
    private readonly store: ChatStore,
    private readonly fetcher: typeof fetch = fetch,
  ) {
    this.oauthConfig = {
      clientId: config.githubClientId,
      clientSecret: config.githubClientSecret,
      authorizeUrl: config.githubOAuthAuthorizeUrl,
      tokenUrl: config.githubOAuthTokenUrl,
      apiUrl: config.githubApiUrl,
    };
    this.keyring = new Map(Object.entries(config.tokenEncryptionKeyring.keys));
  }

  providerFor(actorId: string): GitHubTokenProvider {
    return async () => {
      const link = await this.store.getOAuthLink(actorId);
      if (link === null) {
        throw new AuthenticationError("linked GitHub identity is required");
      }
      let bundle = decryptTokenBundle(link.tokenEnvelope, this.keyring);
      let expiresIn = remainingSeconds(bundle, Date.now());
      if (expiresIn <= SDK_MINIMUM_LIFETIME_SECONDS) {
        bundle = await refreshGitHubToken(this.oauthConfig, bundle, this.fetcher);
        const envelope = encryptTokenBundle(
          bundle,
          currentEncryptionKey(this.config),
          this.config.tokenEncryptionKeyring.currentKeyId,
        );
        await this.store.upsertOAuthLink(
          actorId,
          bundle.githubUserId,
          bundle.githubLogin,
          envelope,
        );
        expiresIn = remainingSeconds(bundle, Date.now());
      }
      if (expiresIn <= SDK_MINIMUM_LIFETIME_SECONDS) {
        throw new AuthenticationError("refreshed GitHub token lifetime is too short");
      }
      return {
        kind: "token",
        accessToken: bundle.accessToken,
        tokenType: bundle.tokenType,
        expiresIn,
      };
    };
  }
}

function currentEncryptionKey(config: ChatConfig): Buffer {
  const key = config.tokenEncryptionKeyring.keys[config.tokenEncryptionKeyring.currentKeyId];
  if (key === undefined) {
    throw new ChatConfigError("current token encryption key is unavailable");
  }
  return key;
}

export class GitHubOAuthFlow {
  private readonly oauthConfig: GitHubOAuthConfig;
  private readonly keyring: ReadonlyMap<string, Buffer>;

  constructor(
    private readonly config: ChatConfig,
    private readonly store: ChatStore,
    private readonly fetcher: typeof fetch = fetch,
  ) {
    this.oauthConfig = {
      clientId: config.githubClientId,
      clientSecret: config.githubClientSecret,
      authorizeUrl: config.githubOAuthAuthorizeUrl,
      tokenUrl: config.githubOAuthTokenUrl,
      apiUrl: config.githubApiUrl,
    };
    this.keyring = new Map(Object.entries(config.tokenEncryptionKeyring.keys));
  }

  async begin(actorId: string): Promise<string> {
    const redirectUri = new URL("/oauth/github/callback", this.config.publicOrigin).toString();
    const state = generateOAuthState(actorId, redirectUri);
    const stateHash = hashOAuthState(state.state, this.config.identityPepper);
    const envelope = encryptOAuthState(
      state,
      currentEncryptionKey(this.config),
      this.config.tokenEncryptionKeyring.currentKeyId,
    );
    await this.store.putOAuthState(actorId, stateHash, envelope, state.expiresAt);
    return buildGitHubAuthorisationUrl(this.oauthConfig, state);
  }

  async complete(actorId: string, rawState: string, code: string): Promise<string> {
    const stateHash = hashOAuthState(rawState, this.config.identityPepper);
    const envelope = await this.store.consumeOAuthState(actorId, stateHash);
    if (envelope === null) {
      throw new AuthenticationError("OAuth state is invalid, expired, or already consumed");
    }
    const state = decryptOAuthState(envelope, this.keyring);
    if (state.actorId !== actorId || state.state !== rawState) {
      throw new AuthenticationError("OAuth state is not bound to this actor");
    }
    const bundle = await exchangeGitHubCode(this.oauthConfig, code, state, this.fetcher);
    const tokenEnvelope = encryptTokenBundle(
      bundle,
      currentEncryptionKey(this.config),
      this.config.tokenEncryptionKeyring.currentKeyId,
    );
    await this.store.upsertOAuthLink(
      actorId,
      bundle.githubUserId,
      bundle.githubLogin,
      tokenEnvelope,
    );
    return bundle.githubLogin;
  }
}
