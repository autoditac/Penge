/**
 * MCP tool: `answer_planning_question`.
 *
 * Generates an explanation-first household-planning report by delegating
 * to the Python `penge.sim.planning_surface_cli` module. The MCP wire
 * stays small: clients choose a local plan id plus question ids, while
 * the Python side runs the household planner and returns linked answers,
 * assumptions, risks, limitations, and documentation references.
 */

import { spawn } from "node:child_process";

import { z } from "zod/v3";

import type { ToolDefinition } from "../registry.js";

const QuestionId = z.enum([
  "can_we_retire",
  "what_breaks_first",
  "how_do_taxes_affect_plan",
  "which_assumptions_matter",
  "which_scenarios_should_we_test",
]);

const DEFAULT_QUESTIONS = [
  "can_we_retire",
  "what_breaks_first",
  "how_do_taxes_affect_plan",
] as const satisfies readonly z.infer<typeof QuestionId>[];

const InputSchema = z
  .object({
    plan_id: z.literal("synthetic_household").default("synthetic_household"),
    questions: z
      .array(QuestionId)
      .min(1)
      .max(5)
      .refine((arr) => new Set(arr).size === arr.length, {
        message: "questions must be unique",
      })
      .default(() => [...DEFAULT_QUESTIONS]),
  })
  .strict();

export type AnswerPlanningQuestionInput = z.infer<typeof InputSchema>;

const AnswerStatus = z.enum(["ready", "watch", "not_ready", "info"]);
const RiskSeverity = z.enum(["info", "warning", "critical"]);

const EvidenceSchema = z
  .object({
    label: z.string().min(1),
    value: z.string().min(1),
    source: z.string().min(1),
  })
  .strict();

const RiskSchema = z
  .object({
    code: z.string().min(1),
    severity: RiskSeverity,
    message: z.string().min(1),
    affected_year: z.number().int().nullable(),
    source_assumption: z.string().min(1),
    next_action: z.string().min(1),
  })
  .strict();

const AssumptionSchema = z
  .object({
    key: z.string().min(1),
    value: z.string().min(1),
    unit: z.string(),
    source: z.string().min(1),
    notes: z.string(),
  })
  .strict();

const LimitationSchema = z
  .object({
    code: z.string().min(1),
    message: z.string().min(1),
    docs: z.array(z.string().min(1)),
  })
  .strict();

const AnswerSchema = z
  .object({
    question_id: QuestionId,
    question: z.string().min(1),
    status: AnswerStatus,
    answer: z.string().min(1),
    evidence: z.array(EvidenceSchema),
    risk_codes: z.array(z.string().min(1)),
    assumption_keys: z.array(z.string().min(1)),
    limitation_codes: z.array(z.string().min(1)),
    docs: z.array(z.string().min(1)),
  })
  .strict();

const OutputSchema = z
  .object({
    plan_id: z.literal("synthetic_household"),
    surface: z.literal("household_planning_questions"),
    generated_by: z.literal("penge.sim.planning_surface"),
    overall_status: AnswerStatus,
    questions: z.array(AnswerSchema).min(1),
    risks: z.array(RiskSchema),
    assumptions: z.array(AssumptionSchema),
    limitations: z.array(LimitationSchema),
    docs: z.array(z.string().min(1)),
  })
  .strict();

export type AnswerPlanningQuestionOutput = z.infer<typeof OutputSchema>;

export interface PlanningSurfaceRunner {
  run(stdinJson: string): Promise<unknown>;
}

export interface AnswerPlanningQuestionOptions {
  runner?: PlanningSurfaceRunner;
  /** Override the Python interpreter. Defaults to `PENGE_PYTHON` env or `python3`. */
  pythonCmd?: string;
  /** Override the module name. Defaults to `penge.sim.planning_surface_cli`. */
  pythonModule?: string;
  /** Working directory for the subprocess. Defaults to `process.cwd()`. */
  cwd?: string;
}

class PlanningSurfaceToolError extends Error {
  override readonly name = "PlanningSurfaceToolError";
  readonly code = "tool/answer_planning_question_failed";
}

function defaultRunner(opts: {
  pythonCmd: string;
  pythonModule: string;
  cwd: string;
}): PlanningSurfaceRunner {
  return {
    async run(stdinJson) {
      const cmdArgs = ["-m", opts.pythonModule];
      return new Promise((resolve, reject) => {
        const child = spawn(opts.pythonCmd, cmdArgs, {
          cwd: opts.cwd,
          stdio: ["pipe", "pipe", "pipe"],
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
              new PlanningSurfaceToolError(
                `penge.sim.planning_surface_cli exited with code ${code}: ${
                  stderr.trim() || "(no stderr)"
                }`,
              ),
            );
            return;
          }
          try {
            resolve(JSON.parse(stdout));
          } catch (cause) {
            reject(
              new PlanningSurfaceToolError(
                `penge.sim.planning_surface_cli emitted non-JSON output: ${
                  (cause as Error).message
                }`,
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

export function answerPlanningQuestionTool(
  opts: AnswerPlanningQuestionOptions = {},
): ToolDefinition<AnswerPlanningQuestionInput, AnswerPlanningQuestionOutput> {
  const pythonCmd = opts.pythonCmd ?? process.env.PENGE_PYTHON ?? "python3";
  const pythonModule = opts.pythonModule ?? "penge.sim.planning_surface_cli";
  const cwd = opts.cwd ?? process.cwd();
  const runner = opts.runner ?? defaultRunner({ pythonCmd, pythonModule, cwd });

  return {
    name: "answer_planning_question",
    description:
      "Answers common household FIRE-planning questions from a local " +
      "HouseholdPlan result. The current built-in plan id is " +
      "`synthetic_household`, which runs a synthetic DK/DE household through " +
      "the Python planner and returns direct answers linked to evidence, " +
      "assumptions, risk findings, model limitations, and docs. Supported " +
      "questions include `can_we_retire`, `what_breaks_first`, " +
      "`how_do_taxes_affect_plan`, `which_assumptions_matter`, and " +
      "`which_scenarios_should_we_test`.",
    inputSchema: InputSchema,
    outputSchema: OutputSchema,
    async handler(args) {
      const raw = await runner.run(JSON.stringify(args));
      return raw as AnswerPlanningQuestionOutput;
    },
  };
}
