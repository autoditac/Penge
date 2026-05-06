---
applyTo: "**/*.{ts,tsx}"
---

# TypeScript instructions

## Toolchain

- Use `pnpm` exclusively. Never `npm`, never `yarn`.
- Lockfile (`pnpm-lock.yaml`) is committed.
- Target Node version is set in `.nvmrc` / `package.json#engines`.

## Style

- TypeScript `strict: true`. No `any`. `unknown` plus narrowing is acceptable.
- Format with Prettier; lint with ESLint (typescript-eslint). Both in pre-commit.
- Use `import type { ... }` for type-only imports.

## Validation

- Validate all runtime inputs (HTTP request bodies, MCP tool args, file parses) with **`zod`** schemas. Never trust `JSON.parse` output untyped.
- Export inferred types from zod schemas: `type Foo = z.infer<typeof FooSchema>`.

## MCP server (`apps/mcp/`)

- Tools are registered with the official `@modelcontextprotocol/sdk`.
- Every tool has a zod input schema, a zod output schema, and a docstring used for the tool description.
- Tools never expose raw bulk data. They return aggregates, summaries, or specific records by ID.
- Every tool call is logged (timestamp, tool name, redacted args) for auditability.

## Errors

- Define `class PengeError extends Error` and subclass per domain. Carry a `code: string` for machine matching.
- Never throw plain strings.

## Tests

- `vitest` for unit and integration tests.
- Mock external HTTP with `msw` or by injecting a fake client; never call real APIs in tests.

## Logging

- Use `pino` with JSON output. Never `console.log` outside CLI entrypoints.
