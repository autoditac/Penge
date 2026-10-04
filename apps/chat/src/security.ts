import { PengeError } from "./errors.js";

export class PromptInjectionError extends PengeError {
  constructor(message: string) {
    super("chat/prompt_injection", message);
    this.name = "PromptInjectionError";
  }
}

export class ToolPolicyError extends PengeError {
  constructor(message: string) {
    super("chat/tool_policy", message);
    this.name = "ToolPolicyError";
  }
}

const INJECTION_PATTERNS = [
  /\bignore (?:all |any |the )?(?:previous|prior|system|developer) instructions?\b/i,
  /\b(?:reveal|print|show|repeat|exfiltrate) (?:the )?(?:system|developer) prompt\b/i,
  /\b(?:override|bypass|disable) (?:the )?(?:tool|security|permission) (?:policy|guard|allowlist)\b/i,
  /\b(?:use|open|run|invoke) (?:a )?(?:shell|terminal|browser|filesystem|sql)\b/i,
] as const;

export function assertPromptIsSafe(prompt: string): void {
  const normalized = prompt.trim();
  if (normalized.length === 0 || normalized.length > 8_000) {
    throw new PromptInjectionError("prompt length is outside the accepted range");
  }
  if (INJECTION_PATTERNS.some((pattern) => pattern.test(normalized))) {
    throw new PromptInjectionError("prompt contains a disallowed instruction override");
  }
}

export function redactedArgumentKeys(args: unknown): string[] {
  if (typeof args !== "object" || args === null || Array.isArray(args)) {
    return [];
  }
  return Object.keys(args)
    .filter((key) => /^[a-zA-Z0-9_.-]{1,64}$/.test(key))
    .sort()
    .slice(0, 32);
}
