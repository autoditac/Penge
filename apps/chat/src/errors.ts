export class PengeError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "PengeError";
    this.code = code;
  }
}

export class ChatConfigError extends PengeError {
  constructor(message: string) {
    super("chat/config", message);
    this.name = "ChatConfigError";
  }
}

export class AuthenticationError extends PengeError {
  constructor(message: string) {
    super("chat/authentication", message);
    this.name = "AuthenticationError";
  }
}

export class AuthorizationError extends PengeError {
  constructor(message: string) {
    super("chat/authorization", message);
    this.name = "AuthorizationError";
  }
}

export class FeatureDisabledError extends PengeError {
  constructor(message: string) {
    super("chat/feature_disabled", message);
    this.name = "FeatureDisabledError";
  }
}

export class HydraFusionUnavailableError extends PengeError {
  constructor(message: string) {
    super("chat/hydrafusion_unavailable", message);
    this.name = "HydraFusionUnavailableError";
  }
}

export class SessionLimitError extends PengeError {
  constructor(message: string) {
    super("chat/session_limit", message);
    this.name = "SessionLimitError";
  }
}

export class DatabasePolicyError extends PengeError {
  constructor(message: string) {
    super("chat/database_policy", message);
    this.name = "DatabasePolicyError";
  }
}

export class CopilotRuntimeError extends PengeError {
  constructor(code: "chat/copilot_timeout" | "chat/copilot_cleanup", message: string) {
    super(code, message);
    this.name = "CopilotRuntimeError";
  }
}

export class ServerStartupError extends PengeError {
  constructor(message: string) {
    super("chat/server_startup", message);
    this.name = "ServerStartupError";
  }
}
