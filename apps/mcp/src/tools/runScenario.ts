/**
 * MCP tool: `run_scenario`.
 *
 * Runs a baseline + scenario Monte-Carlo comparison via the Phase-3
 * scenario engine in `src/penge/sim/scenario.py`. The Python side is
 * invoked as a subprocess so the MCP server (TypeScript) and the
 * simulator (Python + NumPy + Pydantic) stay in their respective
 * worlds.
 *
 * The Python CLI contract lives at `src/penge/sim/run_scenario_cli.py`;
 * see its module docstring for the input JSON shape. This MCP tool
 * forwards the wire-level scenario + monte-carlo overrides on top of a
 * household baseline JSON read from
 * `${PENGE_SIM_INPUTS_DIR:-data/sim}/baseline.json`. The baseline file
 * supplies the per-household configs (cashflow, tax, goal, return
 * model, MC defaults) that the LLM host has no business carrying on
 * the wire.
 */

import { spawn } from "node:child_process";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { z } from "zod";

import type { ToolDefinition } from "../registry.js";

/**
 * Accepts a finite number or a numeric string and validates it against
 * `predicate`. Inputs are passed through unchanged (so Decimal precision
 * survives the wire) — we only parse for validation purposes.
 */
function numericish(predicate: (n: number) => boolean, message: string) {
  return z.union([z.number().finite(), z.string().min(1)]).superRefine((val, ctx) => {
    const n = typeof val === "number" ? val : Number(val);
    if (!Number.isFinite(n)) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, message: "must be a finite number" });
      return;
    }
    if (!predicate(n)) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, message });
    }
  });
}

function asNumber(val: number | string): number {
  return typeof val === "number" ? val : Number(val);
}

const HousePurchaseParams = z
  .object({
    year: z.number().int().gte(2024).lte(2100),
    price_eur: numericish((n) => n > 0, "price_eur must be > 0"),
    downpayment_eur: numericish((n) => n >= 0, "downpayment_eur must be >= 0"),
    mortgage_rate: numericish((n) => n >= 0 && n <= 1, "mortgage_rate must be in [0, 1]"),
    term_years: z.number().int().gte(1).lte(50),
  })
  .strict()
  .refine(
    (p) => {
      const price = asNumber(p.price_eur);
      const down = asNumber(p.downpayment_eur);
      return Number.isFinite(price) && Number.isFinite(down) && down <= price;
    },
    {
      message: "downpayment_eur must be <= price_eur",
      path: ["downpayment_eur"],
    },
  );

const WorkReductionParams = z
  .object({
    entity: z.string().min(1),
    year: z.number().int().gte(2024).lte(2100),
    fte_fraction: numericish((n) => n > 0 && n <= 1, "fte_fraction must be in (0, 1]"),
  })
  .strict();

const InputSchema = z
  .discriminatedUnion("scenario_type", [
    z
      .object({
        scenario_type: z.literal("house_purchase"),
        params: HousePurchaseParams,
        monte_carlo: z
          .object({
            paths: z.number().int().gte(1).lte(100_000),
            seed: z.number().int().optional(),
            horizon_years: z.number().int().gte(1).lte(80),
          })
          .strict(),
      })
      .strict(),
    z
      .object({
        scenario_type: z.literal("work_reduction"),
        params: WorkReductionParams,
        monte_carlo: z
          .object({
            paths: z.number().int().gte(1).lte(100_000),
            seed: z.number().int().optional(),
            horizon_years: z.number().int().gte(1).lte(80),
          })
          .strict(),
      })
      .strict(),
  ])
  .describe("Scenario specification + Monte-Carlo overrides.");

export type RunScenarioInput = z.infer<typeof InputSchema>;

const YearKeyedNumbers = z.record(z.string().regex(/^\d{4}$/), z.number().finite());
const YearKeyedInts = z.record(z.string().regex(/^\d{4}$/), z.number().int().nonnegative());

const SummarySchema = z
  .object({
    p10: YearKeyedNumbers,
    p50: YearKeyedNumbers,
    p90: YearKeyedNumbers,
    fire_year_distribution: YearKeyedInts,
  })
  .strict();

const OutputSchema = z
  .object({
    baseline: SummarySchema,
    scenario: SummarySchema,
    deltas: z
      .object({
        p50_value_eur: z.number().finite().nullable(),
        fire_year_shift_years: z.number().int().nullable(),
      })
      .strict(),
  })
  .strict();

export type RunScenarioOutput = z.infer<typeof OutputSchema>;

/**
 * Spawn-shaped runner so unit tests can inject a fake without
 * launching a real subprocess. Implementations must:
 *   - return the JSON-parsed stdout payload on `code === 0`,
 *   - throw an `Error` on non-zero exit, including stderr in the
 *     message so the audit log captures the failure mode.
 */
export interface ScenarioSubprocessRunner {
  run(stdinJson: string): Promise<unknown>;
}

/**
 * Loader that returns the household baseline spec — everything the CLI
 * needs except the scenario block and `monte_carlo` overrides. Default
 * implementation reads `${PENGE_SIM_INPUTS_DIR:-data/sim}/baseline.json`.
 */
export interface BaselineLoader {
  load(): Record<string, unknown>;
}

export interface RunScenarioOptions {
  runner?: ScenarioSubprocessRunner;
  baselineLoader?: BaselineLoader;
  /** Override the Python interpreter. Defaults to `PENGE_PYTHON` env or `python3`. */
  pythonCmd?: string;
  /** Override the module name. Defaults to `penge.sim.run_scenario_cli`. */
  pythonModule?: string;
  /** Working directory. Defaults to `process.cwd()`. */
  cwd?: string;
}

class RunScenarioError extends Error {
  override readonly name = "RunScenarioError";
  readonly code = "tool/run_scenario_failed";
}

function defaultRunner(opts: {
  pythonCmd: string;
  pythonModule: string;
  cwd: string;
}): ScenarioSubprocessRunner {
  return {
    async run(stdinJson) {
      const cmdArgs = ["-m", opts.pythonModule, "--json"];
      return new Promise((resolveP, rejectP) => {
        const child = spawn(opts.pythonCmd, cmdArgs, {
          cwd: opts.cwd,
          stdio: ["pipe", "pipe", "pipe"],
        });
        const stdoutChunks: Buffer[] = [];
        const stderrChunks: Buffer[] = [];
        child.stdout.on("data", (chunk: Buffer) => stdoutChunks.push(chunk));
        child.stderr.on("data", (chunk: Buffer) => stderrChunks.push(chunk));
        child.on("error", (err) => rejectP(err));
        child.on("close", (code) => {
          const stdout = Buffer.concat(stdoutChunks).toString("utf8");
          const stderr = Buffer.concat(stderrChunks).toString("utf8");
          if (code !== 0) {
            rejectP(
              new RunScenarioError(
                `penge.sim.run_scenario_cli exited with code ${code}: ${
                  stderr.trim() || "(no stderr)"
                }`,
              ),
            );
            return;
          }
          try {
            resolveP(JSON.parse(stdout));
          } catch (cause) {
            rejectP(
              new RunScenarioError(
                `penge.sim.run_scenario_cli emitted non-JSON output: ${(cause as Error).message}`,
              ),
            );
          }
        });
        child.stdin.write(stdinJson);
        child.stdin.end();
      });
    },
  };
}

function defaultBaselineLoader(cwd: string): BaselineLoader {
  return {
    load() {
      const baseDir = process.env.PENGE_SIM_INPUTS_DIR ?? "data/sim";
      const path = resolve(cwd, baseDir, "baseline.json");
      let text: string;
      try {
        text = readFileSync(path, "utf8");
      } catch (cause) {
        throw new RunScenarioError(
          `unable to read scenario baseline from ${path}: ${(cause as Error).message}`,
        );
      }
      let parsed: unknown;
      try {
        parsed = JSON.parse(text);
      } catch (cause) {
        throw new RunScenarioError(
          `scenario baseline at ${path} is not valid JSON: ${(cause as Error).message}`,
        );
      }
      if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new RunScenarioError(
          `scenario baseline at ${path} must be a JSON object at the top level`,
        );
      }
      return parsed as Record<string, unknown>;
    },
  };
}

export function runScenarioTool(
  opts: RunScenarioOptions = {},
): ToolDefinition<RunScenarioInput, RunScenarioOutput> {
  const pythonCmd = opts.pythonCmd ?? process.env.PENGE_PYTHON ?? "python3";
  const pythonModule = opts.pythonModule ?? "penge.sim.run_scenario_cli";
  const cwd = opts.cwd ?? process.cwd();
  const runner = opts.runner ?? defaultRunner({ pythonCmd, pythonModule, cwd });
  const baselineLoader = opts.baselineLoader ?? defaultBaselineLoader(cwd);

  return {
    name: "run_scenario",
    description:
      "Runs a baseline + scenario Monte-Carlo comparison and returns " +
      "p10/p50/p90 portfolio paths plus a FIRE-year histogram for both, " +
      "and a small `deltas` block (terminal-year p50 EUR delta and " +
      "median-FIRE-year shift). Two scenario types are supported: " +
      "`house_purchase` (year, price_eur, downpayment_eur, mortgage_rate, " +
      "term_years) and `work_reduction` (entity, year, fte_fraction). " +
      "The household baseline (cashflow, tax, goal, return model, MC " +
      "defaults) is loaded from " +
      "`${PENGE_SIM_INPUTS_DIR:-data/sim}/baseline.json`; only the " +
      "scenario itself and the `monte_carlo` overrides (paths, seed, " +
      "horizon_years) come from the wire.",
    inputSchema: InputSchema,
    outputSchema: OutputSchema,
    async handler(args) {
      const baseline = baselineLoader.load();
      const spec: Record<string, unknown> = {
        ...baseline,
        scenario: { type: args.scenario_type, params: args.params },
        monte_carlo: args.monte_carlo,
      };
      const stdinJson = JSON.stringify(spec);
      const raw = await runner.run(stdinJson);
      return raw as RunScenarioOutput;
    },
  };
}
