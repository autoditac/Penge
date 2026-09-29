/** Planning: synthetic preview of the MCP-backed planning surface.
 *
 * Cards mirror the `answer_planning_question` MCP tool. The data here is the
 * labelled synthetic preview from `reporting.ts` until the AI review layer
 * (#210) wires live MCP calls through the Copilot SDK boundary.
 */

import Box from "@mui/material/Box";
import Typography from "@mui/material/Typography";

import { PageHeader, Panel, Pill } from "../components/primitives";
import type { Tone } from "../components/primitives";
import { demoDashboard, riskCountBySeverity } from "../reporting";
import type { PlanningQuestion, Risk } from "../reporting";

const questionTone: Record<PlanningQuestion["status"], Tone> = {
  ready: "good",
  watch: "watch",
  info: "info",
};

const riskTone: Record<Risk["severity"], Tone> = {
  info: "info",
  warning: "watch",
  critical: "critical",
};

export function PlanningPage(): React.JSX.Element {
  const warningCount = riskCountBySeverity(demoDashboard.risks, "warning");

  return (
    <>
      <PageHeader
        title="Planning"
        description="Deterministic household reporting stays primary; AI explains linked evidence through the MCP planning surface instead of inventing numbers."
        badge={<Pill tone="info">Synthetic preview — live MCP wiring lands with #210</Pill>}
      />
      <Panel
        eyebrow="AI assistant boundary"
        title="MCP-backed planning questions"
        actions={<Pill tone="good">Copilot SDK compatible</Pill>}
      >
        <Typography color="text.secondary" sx={{ mb: 2 }}>
          These cards mirror the existing <code>answer_planning_question</code> tool. A future
          Copilot SDK agent calls the same typed tool and streams explanations, while the UI keeps
          assumptions, risks, and source links visible.
        </Typography>
        <Box
          sx={{
            display: "grid",
            gap: 1.5,
            gridTemplateColumns: { xs: "1fr", sm: "repeat(auto-fill, minmax(240px, 1fr))" },
          }}
        >
          {demoDashboard.planningQuestions.map((question) => (
            <QuestionCard key={question.id} question={question} />
          ))}
        </Box>
      </Panel>
      <Panel
        eyebrow="Risk register"
        title="Review before deciding"
        actions={<Pill tone="watch">{warningCount} active watch items</Pill>}
      >
        <Box sx={{ display: "flex", flexDirection: "column", gap: 1.25 }}>
          {demoDashboard.risks.map((risk) => (
            <RiskItem key={risk.code} risk={risk} />
          ))}
        </Box>
      </Panel>
    </>
  );
}

function QuestionCard({ question }: { readonly question: PlanningQuestion }): React.JSX.Element {
  return (
    <Box
      sx={{
        border: "1px solid",
        borderColor: "divider",
        borderRadius: 3,
        p: 1.5,
        bgcolor: "background.default",
      }}
    >
      <Pill tone={questionTone[question.status]}>{question.status}</Pill>
      <Typography component="h3" sx={{ fontSize: "1rem", fontWeight: 700, mt: 1, mb: 0.5 }}>
        {question.question}
      </Typography>
      <Typography color="text.secondary" sx={{ fontSize: "0.9rem", mb: 0.75 }}>
        {question.summary}
      </Typography>
      <Typography component="small" color="text.secondary" sx={{ fontSize: "0.78rem" }}>
        {question.evidenceCount} linked evidence items
      </Typography>
    </Box>
  );
}

function RiskItem({ risk }: { readonly risk: Risk }): React.JSX.Element {
  return (
    <Box
      sx={{
        border: "1px solid",
        borderColor: "divider",
        borderRadius: 3,
        p: 1.5,
        bgcolor: "background.default",
        display: "flex",
        flexDirection: "column",
        gap: 0.5,
      }}
    >
      <Pill tone={riskTone[risk.severity]}>{risk.severity}</Pill>
      <Typography component="h3" sx={{ fontSize: "1rem", fontWeight: 700 }}>
        {risk.title}
      </Typography>
      <Typography color="text.secondary" sx={{ fontSize: "0.9rem" }}>
        {risk.nextAction}
      </Typography>
      <Typography component="small" color="text.secondary" sx={{ fontSize: "0.78rem" }}>
        {risk.code}
      </Typography>
    </Box>
  );
}
