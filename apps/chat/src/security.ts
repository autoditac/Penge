import { z } from "zod/v3";

export class PromptInjectionError extends Error {
  override readonly name = "PromptInjectionError";
  readonly code = "chat/prompt_injection";
}

export class ToolPolicyError extends Error {
  override readonly name = "ToolPolicyError";
  readonly code = "chat/tool_policy";
}

export const ToolExecutionPolicySchema = z.object({
  allowlist: z.array(z.string().min(1)),
  sourceAllowlist: z.array(z.string().min(1)).default([]),
  denylist: z
    .array(z.string().min(1))
    .default([
      "shell",
      "filesystem",
      "browser",
      "web",
      "sql",
      "exec",
      "write_file",
      "delete_file",
      "mutate",
    ]),
});

export type ToolExecutionPolicy = z.infer<typeof ToolExecutionPolicySchema>;

export function createToolPolicy(
  allowlist: readonly string[],
  sourceAllowlist: readonly string[] = [],
): ToolExecutionPolicy {
  return ToolExecutionPolicySchema.parse({
    allowlist: [...allowlist],
    sourceAllowlist: [...sourceAllowlist],
  });
}

const INJECTION_PATTERNS = [
  /ignore previous instructions/i,
  /ignore all prior instructions/i,
  /system prompt/i,
  /developer prompt/i,
  /act as if/i,
  /override the tool policy/i,
  /bypass the tool/i,
];

export function assertPromptIsSafe(prompt: string): void {
  if (prompt.trim().length === 0) {
    throw new PromptInjectionError("empty prompt is not allowed");
  }
  if (INJECTION_PATTERNS.some((pattern) => pattern.test(prompt))) {
    throw new PromptInjectionError("prompt contains disallowed instruction override text");
  }
}

export function assertToolAllowed(
  toolName: string,
  policy: ToolExecutionPolicy,
  sourceName?: string,
): void {
  const normalizedTool = toolName.trim().toLowerCase();
  if (normalizedTool.length === 0) {
    throw new ToolPolicyError("blank tool name is not allowed");
  }

  if (policy.denylist.some((blocked) => normalizedTool.includes(blocked.toLowerCase()))) {
    throw new ToolPolicyError(`tool ${toolName} is denied by policy`);
  }

  if (!policy.allowlist.some((allowed) => allowed.toLowerCase() === normalizedTool)) {
    throw new ToolPolicyError(`tool ${toolName} is not on the local allowlist`);
  }

  if (sourceName !== undefined) {
    const normalizedSource = sourceName.trim().toLowerCase();
    if (
      policy.sourceAllowlist.length > 0 &&
      !policy.sourceAllowlist.some((source) => source.toLowerCase() === normalizedSource)
    ) {
      throw new ToolPolicyError(`source ${sourceName} is not on the trusted source allowlist`);
    }
  }
}

export function redactPrompt(prompt: string): string {
  return prompt.replace(/\b(iban|email|name|account|token|secret)\b/gi, "[REDACTED]");
}
