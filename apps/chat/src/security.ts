import { PengeError } from "./errors.js";

export class ToolPolicyError extends PengeError {
  constructor(message: string) {
    super("chat/tool_policy", message);
    this.name = "ToolPolicyError";
  }
}

export function assertPromptIsSafe(prompt: string): void {
  const normalized = prompt.trim();
  if (normalized.length === 0 || normalized.length > 8_000) {
    throw new PengeError("chat/invalid_prompt", "prompt length is outside the accepted range");
  }
}
