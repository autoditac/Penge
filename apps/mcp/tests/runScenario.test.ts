import { mkdirSync, writeFileSync, rmSync } from "node:fs";
import { resolve } from "node:path";
import { spawn, spawnSync } from "node:child_process";

import { afterAll, beforeAll, describe, expect, it } from "vitest";

import {
  runScenarioTool,
  type RunScenarioInput,
  type ScenarioSubprocessRunner,
  type BaselineLoader,
} from "../src/tools/runScenario.js";

const ctx = { serverName: "test", serverVersion: "0.0.0-test" };

const baseArgs: RunScenarioInput = {
  scenario_type: "work_reduction",
  params: { entity: "person_dk", year: 2027, fte_fraction: "0.8" },
  monte_carlo: { paths: 50, seed: 42, horizon_years: 10 },
};

interface CapturedCall {
  stdinJson: string;
}

function makeRunner(payload: unknown): ScenarioSubprocessRunner & { calls: CapturedCall[] } {
  const calls: CapturedCall[] = [];
  return {
    calls,
    async run(stdinJson) {
      calls.push({ stdinJson });
      return payload;
    },
  };
}

const SAMPLE_BASELINE: Record<string, unknown> = {
  cashflow: {
    base_year: 2024,
    horizon_years: 10,
    inflation_rate: "0.02",
    eur_per_dkk: "0.134",
    salaries: [{ entity: "person_dk", gross_annual: "80000" }],
    contributions: [],
    pension_rules: [],
  },
  tax: {},
  goal: { target_annual_eur: "50000" },
  return_model: {
    asset_returns: { equity: Array.from({ length: 120 }, () => "0.005") },
    inflation: { dk: Array.from({ length: 120 }, () => "0.002") },
    block_months: 12,
    seed: 42,
  },
  mc: {
    n_paths: 50,
    asset_weights: { equity: "1" },
    initial_portfolio_eur: "200000",
  },
};

function fakeLoader(): BaselineLoader {
  return { load: () => structuredClone(SAMPLE_BASELINE) };
}

const SAMPLE_SUMMARY = {
  p10: { "2025": 1, "2034": 100 },
  p50: { "2025": 2, "2034": 200 },
  p90: { "2025": 3, "2034": 300 },
  fire_year_distribution: {},
};
const SAMPLE_PAYLOAD = {
  baseline: SAMPLE_SUMMARY,
  scenario: SAMPLE_SUMMARY,
  deltas: { p50_value_eur: 0, fire_year_shift_years: null },
};

describe("run_scenario — schema validation", () => {
  it("accepts a well-formed work_reduction payload", () => {
    const tool = runScenarioTool({
      runner: makeRunner(SAMPLE_PAYLOAD),
      baselineLoader: fakeLoader(),
    });
    expect(() => tool.inputSchema.parse(baseArgs)).not.toThrow();
  });

  it("accepts a well-formed house_purchase payload", () => {
    const tool = runScenarioTool({
      runner: makeRunner(SAMPLE_PAYLOAD),
      baselineLoader: fakeLoader(),
    });
    expect(() =>
      tool.inputSchema.parse({
        scenario_type: "house_purchase",
        params: {
          year: 2026,
          price_eur: "300000",
          downpayment_eur: "60000",
          mortgage_rate: "0.02",
          term_years: 20,
        },
        monte_carlo: { paths: 50, horizon_years: 10 },
      }),
    ).not.toThrow();
  });

  it("rejects unknown scenario_type", () => {
    const tool = runScenarioTool({
      runner: makeRunner(SAMPLE_PAYLOAD),
      baselineLoader: fakeLoader(),
    });
    expect(() =>
      tool.inputSchema.parse({ ...baseArgs, scenario_type: "magic" } as unknown),
    ).toThrow();
  });

  it("rejects house_purchase params with unknown keys (strict)", () => {
    const tool = runScenarioTool({
      runner: makeRunner(SAMPLE_PAYLOAD),
      baselineLoader: fakeLoader(),
    });
    expect(() =>
      tool.inputSchema.parse({
        scenario_type: "house_purchase",
        params: {
          year: 2026,
          price_eur: "300000",
          downpayment_eur: "60000",
          mortgage_rate: "0.02",
          term_years: 20,
          rogue: 1,
        },
        monte_carlo: { paths: 50, horizon_years: 10 },
      }),
    ).toThrow();
  });

  it("rejects monte_carlo.paths out of range", () => {
    const tool = runScenarioTool({
      runner: makeRunner(SAMPLE_PAYLOAD),
      baselineLoader: fakeLoader(),
    });
    expect(() =>
      tool.inputSchema.parse({
        ...baseArgs,
        monte_carlo: { paths: 0, horizon_years: 10 },
      }),
    ).toThrow();
  });

  it("rejects horizon_years out of range", () => {
    const tool = runScenarioTool({
      runner: makeRunner(SAMPLE_PAYLOAD),
      baselineLoader: fakeLoader(),
    });
    expect(() =>
      tool.inputSchema.parse({
        ...baseArgs,
        monte_carlo: { paths: 50, horizon_years: 200 },
      }),
    ).toThrow();
  });

  it("rejects extra top-level keys (strict)", () => {
    const tool = runScenarioTool({
      runner: makeRunner(SAMPLE_PAYLOAD),
      baselineLoader: fakeLoader(),
    });
    expect(() => tool.inputSchema.parse({ ...baseArgs, extra: 1 })).toThrow();
  });

  it("output schema rejects non-4-digit year keys", () => {
    const tool = runScenarioTool({
      runner: makeRunner(SAMPLE_PAYLOAD),
      baselineLoader: fakeLoader(),
    });
    const bad = {
      baseline: {
        p10: { foo: 1 },
        p50: {},
        p90: {},
        fire_year_distribution: {},
      },
      scenario: SAMPLE_SUMMARY,
      deltas: { p50_value_eur: null, fire_year_shift_years: null },
    };
    expect(() => tool.outputSchema.parse(bad)).toThrow();
  });
});

describe("run_scenario — subprocess invocation (mocked)", () => {
  it("forwards baseline + scenario + monte_carlo to the CLI on stdin", async () => {
    const runner = makeRunner(SAMPLE_PAYLOAD);
    const tool = runScenarioTool({ runner, baselineLoader: fakeLoader() });
    const result = await tool.handler(baseArgs, ctx);
    expect(runner.calls).toHaveLength(1);
    const piped = JSON.parse(runner.calls[0]!.stdinJson) as Record<string, unknown>;
    expect(piped).toMatchObject({
      cashflow: SAMPLE_BASELINE.cashflow,
      goal: SAMPLE_BASELINE.goal,
      mc: SAMPLE_BASELINE.mc,
      scenario: { type: "work_reduction", params: baseArgs.params },
      monte_carlo: baseArgs.monte_carlo,
    });
    const validated = tool.outputSchema.parse(result);
    expect(validated.deltas.p50_value_eur).toBe(0);
  });

  it("propagates subprocess errors", async () => {
    const runner: ScenarioSubprocessRunner = {
      async run() {
        throw new Error("penge.sim.run_scenario_cli exited with code 2: bad input");
      },
    };
    const tool = runScenarioTool({ runner, baselineLoader: fakeLoader() });
    await expect(tool.handler(baseArgs, ctx)).rejects.toThrow(/exited with code 2/);
  });

  it("surfaces baseline-loader failures", async () => {
    const tool = runScenarioTool({
      runner: makeRunner(SAMPLE_PAYLOAD),
      baselineLoader: {
        load: () => {
          throw new Error("unable to read scenario baseline");
        },
      },
    });
    await expect(tool.handler(baseArgs, ctx)).rejects.toThrow(/scenario baseline/);
  });
});

// Integration: spawn the real Python CLI with a synthetic baseline.
const HAS_UV = (() => {
  try {
    const r = spawnSync("uv", ["--version"], { stdio: "ignore" });
    return r.status === 0;
  } catch {
    return false;
  }
})();

const repoRoot = resolve(__dirname, "..", "..", "..");
const scratchDir = resolve(__dirname, ".scratch", "run-scenario");

describe.skipIf(!HAS_UV)("run_scenario — integration (real subprocess)", () => {
  beforeAll(() => {
    mkdirSync(scratchDir, { recursive: true });
    writeFileSync(resolve(scratchDir, "baseline.json"), JSON.stringify(SAMPLE_BASELINE));
  });
  afterAll(() => {
    try {
      rmSync(scratchDir, { recursive: true, force: true });
    } catch {
      /* ignore */
    }
  });

  it("returns a deterministic summary for a fixed seed", async () => {
    const prev = process.env.PENGE_SIM_INPUTS_DIR;
    process.env.PENGE_SIM_INPUTS_DIR = scratchDir;
    try {
      const realRunner: ScenarioSubprocessRunner = {
        async run(stdinJson) {
          return new Promise((resolveP, rejectP) => {
            const child = spawn(
              "uv",
              ["run", "python", "-m", "penge.sim.run_scenario_cli", "--json"],
              {
                cwd: repoRoot,
                env: { ...process.env, PENGE_SIM_INPUTS_DIR: scratchDir },
                stdio: ["pipe", "pipe", "pipe"],
              },
            );
            const out: Buffer[] = [];
            const err: Buffer[] = [];
            child.stdout.on("data", (c: Buffer) => out.push(c));
            child.stderr.on("data", (c: Buffer) => err.push(c));
            child.on("error", rejectP);
            child.on("close", (code) => {
              if (code !== 0) {
                rejectP(new Error(`exit ${code}: ${Buffer.concat(err).toString()}`));
                return;
              }
              resolveP(JSON.parse(Buffer.concat(out).toString()));
            });
            child.stdin.write(stdinJson);
            child.stdin.end();
          });
        },
      };
      const tool = runScenarioTool({ runner: realRunner });
      const a = tool.outputSchema.parse(await tool.handler(baseArgs, ctx));
      const b = tool.outputSchema.parse(await tool.handler(baseArgs, ctx));
      expect(a).toEqual(b);
      expect(Object.keys(a.baseline.p50).length).toBe(10);
    } finally {
      if (prev === undefined) {
        delete process.env.PENGE_SIM_INPUTS_DIR;
      } else {
        process.env.PENGE_SIM_INPUTS_DIR = prev;
      }
    }
  }, 60_000);
});
