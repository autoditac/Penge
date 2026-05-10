import { resolve } from "node:path";
import { spawn, spawnSync } from "node:child_process";

import { describe, expect, it } from "vitest";

import {
  computeTaxYearTool,
  type ComputeTaxYearInput,
  type SubprocessRunner,
} from "../src/tools/computeTaxYear.js";

const ctx = { serverName: "test", serverVersion: "0.0.0-test" };

const baseArgs: ComputeTaxYearInput = {
  year: 2024,
  jurisdictions: ["DK", "DE"],
  currency: "EUR",
};

interface CapturedCall {
  args: ReadonlyArray<string>;
}

function makeRunner(payload: unknown): SubprocessRunner & { calls: CapturedCall[] } {
  const calls: CapturedCall[] = [];
  return {
    calls,
    async run(args) {
      calls.push({ args });
      return payload;
    },
  };
}

describe("compute_tax_year — schema validation", () => {
  it("accepts a well-formed payload", () => {
    const tool = computeTaxYearTool({ runner: makeRunner([]) });
    expect(() => tool.inputSchema.parse(baseArgs)).not.toThrow();
  });

  it("rejects unknown jurisdiction", () => {
    const tool = computeTaxYearTool({ runner: makeRunner([]) });
    expect(() => tool.inputSchema.parse({ ...baseArgs, jurisdictions: ["DK", "US"] })).toThrow();
  });

  it("rejects empty jurisdictions array", () => {
    const tool = computeTaxYearTool({ runner: makeRunner([]) });
    expect(() => tool.inputSchema.parse({ ...baseArgs, jurisdictions: [] })).toThrow();
  });

  it("rejects duplicate jurisdictions", () => {
    const tool = computeTaxYearTool({ runner: makeRunner([]) });
    expect(() => tool.inputSchema.parse({ ...baseArgs, jurisdictions: ["DK", "DK"] })).toThrow(
      /unique/,
    );
  });

  it("rejects unknown currency", () => {
    const tool = computeTaxYearTool({ runner: makeRunner([]) });
    expect(() => tool.inputSchema.parse({ ...baseArgs, currency: "USD" })).toThrow();
  });

  it("rejects out-of-range year", () => {
    const tool = computeTaxYearTool({ runner: makeRunner([]) });
    expect(() => tool.inputSchema.parse({ ...baseArgs, year: 1800 })).toThrow();
    expect(() => tool.inputSchema.parse({ ...baseArgs, year: 3000 })).toThrow();
  });

  it("rejects extra keys (strict)", () => {
    const tool = computeTaxYearTool({ runner: makeRunner([]) });
    expect(() => tool.inputSchema.parse({ ...baseArgs, extra: 1 })).toThrow();
  });
});

describe("compute_tax_year — subprocess invocation (mocked)", () => {
  it("forwards year/currency/jurisdictions to the CLI as flags", async () => {
    const payload = [
      {
        year: 2024,
        jurisdiction: "DK",
        currency: "EUR",
        summary: { gross_capital_income: 0 },
        line_items: [],
      },
      {
        year: 2024,
        jurisdiction: "DE",
        currency: "EUR",
        summary: { total_tax_due: 0 },
        line_items: [],
      },
    ];
    const runner = makeRunner(payload);
    const tool = computeTaxYearTool({ runner });
    const result = await tool.handler(baseArgs, ctx);
    expect(runner.calls).toHaveLength(1);
    expect(runner.calls[0]!.args).toEqual([
      "--year",
      "2024",
      "--currency",
      "EUR",
      "--jurisdictions",
      "DK,DE",
    ]);
    const validated = tool.outputSchema.parse(result);
    expect(validated.map((r) => r.jurisdiction)).toEqual(["DK", "DE"]);
  });

  it("validates the runner's output against the wire schema", async () => {
    const runner = makeRunner([
      {
        year: 2024,
        jurisdiction: "DK",
        currency: "EUR",
        summary: { gross_capital_income: 1000 },
        line_items: [{ category: "lager", amount: 1000, source: "lager:n:DK0001234567" }],
      },
    ]);
    const tool = computeTaxYearTool({ runner });
    const result = await tool.handler({ year: 2024, jurisdictions: ["DK"], currency: "EUR" }, ctx);
    const parsed = tool.outputSchema.parse(result);
    expect(parsed[0]!.line_items[0]!.source).toBe("lager:n:DK0001234567");
  });

  it("rejects shapes the CLI was not supposed to emit (output schema is strict)", () => {
    const tool = computeTaxYearTool({ runner: makeRunner([]) });
    expect(() =>
      tool.outputSchema.parse([
        {
          year: 2024,
          jurisdiction: "DK",
          currency: "EUR",
          summary: { gross_capital_income: 0 },
          line_items: [],
          // Schema is strict — extra wire fields must be rejected.
          rogue: "should_not_be_here",
        },
      ]),
    ).toThrow();
  });

  it("propagates subprocess errors", async () => {
    const runner: SubprocessRunner = {
      async run() {
        throw new Error("penge.tax CLI exited with code 2: invalid JSON");
      },
    };
    const tool = computeTaxYearTool({ runner });
    await expect(tool.handler(baseArgs, ctx)).rejects.toThrow(/exited with code 2/);
  });
});

// Integration: spawn the real Python CLI with a synthetic dataset.
// `uv` isn't always present in CI sandboxes; skip cleanly when it is
// not. The CLI's own pytest suite (`tests/tax/test_cli.py`) covers
// the calculator semantics — here we only verify that the spawn-shaped
// runner round-trips with the real subprocess.
const HAS_UV = (() => {
  try {
    const r = spawnSync("uv", ["--version"], { stdio: "ignore" });
    return r.status === 0;
  } catch {
    return false;
  }
})();

describe.skipIf(!HAS_UV)("compute_tax_year — integration (real subprocess)", () => {
  it("returns zero reports for an empty inputs dir", async () => {
    const repoRoot = resolve(__dirname, "..", "..", "..");
    const emptyInputsDir = resolve(__dirname, ".scratch", "empty-tax-inputs");
    // Use a directory we know has no <year>.json so the CLI takes the
    // "no inputs → empty report" branch.
    process.env.PENGE_TAX_INPUTS_DIR = emptyInputsDir;
    const tool = computeTaxYearTool({
      pythonCmd: "uv",
      pythonModule: "penge.tax",
      cwd: repoRoot,
    });
    // `uv run python -m penge.tax ...` — adapt the runner: when
    // pythonCmd is `uv`, prepend `run python` to the spawn args.
    // For this test we instead use the explicit interpreter shipped
    // by uv via `uv run`, by overriding the runner.
    const realRunner = {
      async run(args: ReadonlyArray<string>): Promise<unknown> {
        return new Promise((resolveP, rejectP) => {
          const child = spawn("uv", ["run", "python", "-m", "penge.tax", ...args], {
            cwd: repoRoot,
            env: { ...process.env, PENGE_TAX_INPUTS_DIR: emptyInputsDir },
            stdio: ["ignore", "pipe", "pipe"],
          });
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
        });
      },
    };
    const tool2 = computeTaxYearTool({ runner: realRunner });
    const result = await tool2.handler(
      { year: 2024, jurisdictions: ["DK", "DE"], currency: "DKK" },
      ctx,
    );
    const parsed = tool.outputSchema.parse(result);
    expect(parsed).toHaveLength(2);
    expect(parsed.every((r) => r.line_items.length === 0)).toBe(true);
  }, 30_000);
});
