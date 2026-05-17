/**
 * MCP tool: `compute_tax_year`.
 *
 * Computes a per-jurisdiction tax report for a single tax year by
 * delegating to the Python tax calculators in `penge.tax`. The Python
 * side is invoked as a subprocess so the MCP server (TypeScript) and
 * the calculators (Python, with all their Pydantic validation and
 * fixed-point arithmetic) stay in their respective worlds.
 *
 * The Python CLI contract lives at `src/penge/tax/cli.py`; see its
 * module docstring for the input JSON shape and the env-var-driven
 * default input file lookup. This MCP tool only forwards the three
 * wire arguments — `year`, `jurisdictions`, `currency` — and lets the
 * CLI resolve the household's holdings from
 * `${PENGE_TAX_INPUTS_DIR:-data/tax}/<year>.json`.
 *
 * The Python interpreter and module are configurable so the same code
 * runs both under `uv run` in dev and a direct `python3` in production
 * containers.
 */

import { spawn } from "node:child_process";

import { z } from "zod/v3";

import type { ToolDefinition } from "../registry.js";

const Currency = z.enum(["EUR", "DKK"]);
const Jurisdiction = z.enum(["DK", "DE"]);

const InputSchema = z
  .object({
    year: z.number().int().gte(1900).lte(2999),
    jurisdictions: z
      .array(Jurisdiction)
      .min(1)
      .refine((arr) => new Set(arr).size === arr.length, {
        message: "jurisdictions must be unique",
      }),
    currency: Currency,
  })
  .strict();

export type ComputeTaxYearInput = z.infer<typeof InputSchema>;

const LineItemSchema = z
  .object({
    category: z.string().min(1),
    amount: z.number().finite(),
    source: z.string().min(1),
  })
  .strict();

const ReportSchema = z
  .object({
    year: z.number().int(),
    jurisdiction: Jurisdiction,
    currency: Currency,
    summary: z.record(z.string(), z.number().finite()),
    line_items: z.array(LineItemSchema),
  })
  .strict();

const OutputSchema = z.array(ReportSchema);

export type ComputeTaxYearOutput = z.infer<typeof OutputSchema>;

/**
 * Spawn-shaped runner so unit tests can inject a fake without
 * launching a real subprocess. Implementations must:
 *   - return the JSON-parsed stdout payload on `code === 0`,
 *   - throw an `Error` on non-zero exit, including stderr in the
 *     message so the audit log captures the failure mode.
 */
export interface SubprocessRunner {
  run(args: ReadonlyArray<string>): Promise<unknown>;
}

export interface ComputeTaxYearOptions {
  runner?: SubprocessRunner;
  /**
   * Override the Python interpreter command. Defaults to the
   * `PENGE_PYTHON` env var if set, otherwise `python3`. The full
   * invocation is `<python> -m penge.tax <args...>`.
   */
  pythonCmd?: string;
  /** Override the module name. Defaults to `penge.tax`. */
  pythonModule?: string;
  /** Working directory for the subprocess. Defaults to `process.cwd()`. */
  cwd?: string;
}

class TaxCalcError extends Error {
  override readonly name = "TaxCalcError";
  readonly code = "tool/compute_tax_year_failed";
}

function defaultRunner(opts: {
  pythonCmd: string;
  pythonModule: string;
  cwd: string;
}): SubprocessRunner {
  return {
    async run(args) {
      const cmdArgs = ["-m", opts.pythonModule, ...args];
      return new Promise((resolve, reject) => {
        const child = spawn(opts.pythonCmd, cmdArgs, {
          cwd: opts.cwd,
          stdio: ["ignore", "pipe", "pipe"],
        });
        const stdoutChunks: Buffer[] = [];
        const stderrChunks: Buffer[] = [];
        child.stdout.on("data", (chunk: Buffer) => stdoutChunks.push(chunk));
        child.stderr.on("data", (chunk: Buffer) => stderrChunks.push(chunk));
        child.on("error", (err) => reject(err));
        child.on("close", (code) => {
          const stdout = Buffer.concat(stdoutChunks).toString("utf8");
          const stderr = Buffer.concat(stderrChunks).toString("utf8");
          if (code !== 0) {
            reject(
              new TaxCalcError(
                `penge.tax CLI exited with code ${code}: ${stderr.trim() || "(no stderr)"}`,
              ),
            );
            return;
          }
          try {
            resolve(JSON.parse(stdout));
          } catch (cause) {
            reject(
              new TaxCalcError(
                `penge.tax CLI emitted non-JSON output: ${(cause as Error).message}`,
              ),
            );
          }
        });
      });
    },
  };
}

export function computeTaxYearTool(
  opts: ComputeTaxYearOptions = {},
): ToolDefinition<ComputeTaxYearInput, ComputeTaxYearOutput> {
  const pythonCmd = opts.pythonCmd ?? process.env.PENGE_PYTHON ?? "python3";
  const pythonModule = opts.pythonModule ?? "penge.tax";
  const cwd = opts.cwd ?? process.cwd();
  const runner = opts.runner ?? defaultRunner({ pythonCmd, pythonModule, cwd });

  return {
    name: "compute_tax_year",
    description:
      "Computes a per-jurisdiction (DK / DE) tax report for one tax year. " +
      "DK covers lagerbeskatning, Aktiesparekonto (17 %), and PAL-skat " +
      "(15.3 % on pension returns). DE covers Vorabpauschale + " +
      "Teilfreistellung. Returns one report per requested jurisdiction, " +
      "with summary totals and traceable line items in the requested " +
      "currency. Holdings are read from " +
      "`${PENGE_TAX_INPUTS_DIR:-data/tax}/<year>.json`; if absent, the " +
      "report is empty (zero totals) rather than an error.",
    inputSchema: InputSchema,
    outputSchema: OutputSchema,
    async handler(args) {
      const cliArgs = [
        "--year",
        String(args.year),
        "--currency",
        args.currency,
        "--jurisdictions",
        args.jurisdictions.join(","),
      ];
      const raw = await runner.run(cliArgs);
      return raw as ComputeTaxYearOutput;
    },
  };
}
