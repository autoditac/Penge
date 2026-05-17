import { spawn, spawnSync } from "node:child_process";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import {
  answerPlanningQuestionTool,
  type PlanningSurfaceRunner,
} from "../src/tools/answerPlanningQuestion.js";
import { PLANNING_SURFACE_PAYLOAD } from "../evals/fixtures/planningPayloads.js";

const ctx = { serverName: "test", serverVersion: "0.0.0-test" };

function makeRunner(payload: unknown): PlanningSurfaceRunner & { calls: string[] } {
  const calls: string[] = [];
  return {
    calls,
    async run(stdinJson) {
      calls.push(stdinJson);
      return payload;
    },
  };
}

describe("answer_planning_question — schema validation", () => {
  it("accepts default synthetic-household input", () => {
    const tool = answerPlanningQuestionTool({ runner: makeRunner(PLANNING_SURFACE_PAYLOAD) });

    const parsed = tool.inputSchema.parse({});

    expect(parsed.plan_id).toBe("synthetic_household");
    expect(parsed.questions).toEqual([
      "can_we_retire",
      "what_breaks_first",
      "how_do_taxes_affect_plan",
    ]);
  });

  it("rejects duplicate question ids", () => {
    const tool = answerPlanningQuestionTool({ runner: makeRunner(PLANNING_SURFACE_PAYLOAD) });

    expect(() =>
      tool.inputSchema.parse({
        plan_id: "synthetic_household",
        questions: ["can_we_retire", "can_we_retire"],
      }),
    ).toThrow(/questions must be unique/);
  });

  it("rejects unknown plan ids and extra keys", () => {
    const tool = answerPlanningQuestionTool({ runner: makeRunner(PLANNING_SURFACE_PAYLOAD) });

    expect(() => tool.inputSchema.parse({ plan_id: "real_household" })).toThrow();
    expect(() => tool.inputSchema.parse({ extra: true })).toThrow();
  });

  it("output schema requires linked answer details", () => {
    const tool = answerPlanningQuestionTool({ runner: makeRunner(PLANNING_SURFACE_PAYLOAD) });

    const parsed = tool.outputSchema.parse(PLANNING_SURFACE_PAYLOAD);

    expect(parsed.questions[0]?.evidence.length).toBeGreaterThan(0);
    expect(parsed.assumptions[0]?.key).toBe("planned_retirement_year");
    expect(parsed.risks[0]?.code).toBe("de_vorabpauschale_not_in_household_plan");
  });
});

describe("answer_planning_question — subprocess invocation (mocked)", () => {
  it("forwards plan id and requested questions to the Python CLI on stdin", async () => {
    const runner = makeRunner(PLANNING_SURFACE_PAYLOAD);
    const tool = answerPlanningQuestionTool({ runner });

    const result = await tool.handler(
      {
        plan_id: "synthetic_household",
        questions: ["can_we_retire", "which_assumptions_matter"],
      },
      ctx,
    );

    expect(runner.calls).toHaveLength(1);
    expect(JSON.parse(runner.calls[0]!)).toEqual({
      plan_id: "synthetic_household",
      questions: ["can_we_retire", "which_assumptions_matter"],
    });
    expect(result.plan_id).toBe("synthetic_household");
  });

  it("propagates subprocess errors", async () => {
    const runner: PlanningSurfaceRunner = {
      async run() {
        throw new Error("planning surface exited with code 2: bad input");
      },
    };
    const tool = answerPlanningQuestionTool({ runner });

    await expect(
      tool.handler(
        {
          plan_id: "synthetic_household",
          questions: ["can_we_retire"],
        },
        ctx,
      ),
    ).rejects.toThrow(/bad input/);
  });
});

const HAS_UV = (() => {
  try {
    const r = spawnSync("uv", ["--version"], { stdio: "ignore" });
    return r.status === 0;
  } catch {
    return false;
  }
})();

const repoRoot = resolve(__dirname, "..", "..", "..");

describe.skipIf(!HAS_UV)("answer_planning_question — integration (real subprocess)", () => {
  it("runs the Python planning surface for the synthetic household", async () => {
    const realRunner: PlanningSurfaceRunner = {
      async run(stdinJson) {
        return new Promise((resolveP, rejectP) => {
          const child = spawn(
            "uv",
            ["run", "python", "-m", "penge.sim.planning_surface_cli", "--json"],
            {
              cwd: repoRoot,
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
    const tool = answerPlanningQuestionTool({ runner: realRunner });

    const result = tool.outputSchema.parse(
      await tool.handler(
        {
          plan_id: "synthetic_household",
          questions: ["can_we_retire", "how_do_taxes_affect_plan"],
        },
        ctx,
      ),
    );

    expect(result.questions).toHaveLength(2);
    expect(result.risks.length).toBeGreaterThan(0);
    expect(result.assumptions.length).toBeGreaterThan(0);
  }, 60_000);
});
