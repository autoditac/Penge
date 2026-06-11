/** Planning: synthetic preview of the MCP-backed planning surface.
 *
 * Cards mirror the `answer_planning_question` MCP tool. The data here is the
 * labelled synthetic preview from `reporting.ts` until the AI review layer
 * (#210) wires live MCP calls through the Copilot SDK boundary.
 */

import { demoDashboard, riskCountBySeverity } from "../reporting";
import type { PlanningQuestion, Risk } from "../reporting";

export function PlanningPage(): React.JSX.Element {
  const warningCount = riskCountBySeverity(demoDashboard.risks, "warning");

  return (
    <>
      <section className="pageIntro">
        <h1>Planning</h1>
        <p>
          Deterministic household reporting stays primary; AI explains linked evidence through the
          MCP planning surface instead of inventing numbers.
        </p>
        <span className="demoBadge">Synthetic preview — live MCP wiring lands with #210</span>
      </section>
      <section className="panel">
        <div className="panelHeader">
          <div>
            <p className="eyebrow">AI assistant boundary</p>
            <h2>MCP-backed planning questions</h2>
          </div>
          <span className="pill">Copilot SDK compatible</span>
        </div>
        <p className="supporting">
          These cards mirror the existing <code>answer_planning_question</code> tool. A future
          Copilot SDK agent calls the same typed tool and streams explanations, while the UI keeps
          assumptions, risks, and source links visible.
        </p>
        <div className="questionGrid">
          {demoDashboard.planningQuestions.map((question) => (
            <QuestionCard key={question.id} question={question} />
          ))}
        </div>
      </section>
      <section className="panel">
        <div className="panelHeader">
          <div>
            <p className="eyebrow">Risk register</p>
            <h2>Review before deciding</h2>
          </div>
          <span className="pill">{warningCount} active watch items</span>
        </div>
        <div className="riskList">
          {demoDashboard.risks.map((risk) => (
            <RiskItem key={risk.code} risk={risk} />
          ))}
        </div>
      </section>
    </>
  );
}

function QuestionCard({ question }: { readonly question: PlanningQuestion }): React.JSX.Element {
  return (
    <div className={`questionCard status-${question.status}`}>
      <span>{question.status}</span>
      <h3>{question.question}</h3>
      <p>{question.summary}</p>
      <small>{question.evidenceCount} linked evidence items</small>
    </div>
  );
}

function RiskItem({ risk }: { readonly risk: Risk }): React.JSX.Element {
  return (
    <div className={`riskItem severity-${risk.severity}`}>
      <span>{risk.severity}</span>
      <h3>{risk.title}</h3>
      <p>{risk.nextAction}</p>
      <small>{risk.code}</small>
    </div>
  );
}
