import { demoDashboard, formatMetricValue, liquidityShare, riskCountBySeverity } from "./reporting";
import type {
  DashboardMetric,
  MetricTone,
  PlanningQuestion,
  Risk,
  TimelinePoint,
} from "./reporting";
import "./styles.css";

const toneLabels: Record<MetricTone, string> = {
  good: "Ready",
  watch: "Watch",
  critical: "Critical",
  info: "Info",
};

function App(): React.JSX.Element {
  const warningCount = riskCountBySeverity(demoDashboard.risks, "warning");

  return (
    <main className="shell">
      <header className="hero">
        <p className="eyebrow">Penge WebUI</p>
        <div className="heroGrid">
          <div>
            <h1>Reporting-first FIRE cockpit</h1>
            <p>
              Deterministic household reporting stays primary; AI explains linked evidence through
              the MCP planning surface instead of inventing numbers.
            </p>
          </div>
          <div className="statusCard" aria-label="Current dashboard status">
            <span>{demoDashboard.householdLabel}</span>
            <strong>{warningCount} active watch item</strong>
            <small>Generated {new Date(demoDashboard.generatedAt).toLocaleString("en-DK")}</small>
          </div>
        </div>
      </header>

      <section className="metricsGrid" aria-label="Key reporting metrics">
        {demoDashboard.metrics.map((metric) => (
          <MetricCard key={metric.id} metric={metric} />
        ))}
      </section>

      <section className="dashboardGrid">
        <article className="panel spanTwo">
          <div className="panelHeader">
            <div>
              <p className="eyebrow">Classical reporting</p>
              <h2>Net worth and liquidity runway</h2>
            </div>
            <span className="pill">EUR + DKK ready</span>
          </div>
          <ProjectionChart points={demoDashboard.timeline} />
        </article>

        <article className="panel">
          <p className="eyebrow">Risk register</p>
          <h2>Review before deciding</h2>
          <div className="riskList">
            {demoDashboard.risks.map((risk) => (
              <RiskItem key={risk.code} risk={risk} />
            ))}
          </div>
        </article>

        <article className="panel spanTwo">
          <div className="panelHeader">
            <div>
              <p className="eyebrow">AI assistant boundary</p>
              <h2>MCP-backed planning questions</h2>
            </div>
            <span className="pill">Copilot SDK compatible</span>
          </div>
          <p className="supporting">
            These cards mirror the existing <code>answer_planning_question</code> tool. A future
            Copilot SDK agent should call the same typed tool and stream explanations, while the UI
            keeps assumptions, risks, and source links visible.
          </p>
          <div className="questionGrid">
            {demoDashboard.planningQuestions.map((question) => (
              <QuestionCard key={question.id} question={question} />
            ))}
          </div>
        </article>
      </section>
    </main>
  );
}

function MetricCard({ metric }: { readonly metric: DashboardMetric }): React.JSX.Element {
  return (
    <article className={`metricCard tone-${metric.tone}`}>
      <div className="metricTopline">
        <span>{metric.label}</span>
        <strong>{toneLabels[metric.tone]}</strong>
      </div>
      <p className="metricValue">{formatMetricValue(metric)}</p>
      <p className="metricDelta">{metric.deltaLabel}</p>
      <small>{metric.evidence}</small>
    </article>
  );
}

function ProjectionChart({
  points,
}: {
  readonly points: readonly TimelinePoint[];
}): React.JSX.Element {
  const maxNetWorth = Math.max(...points.map((point) => point.netWorthDkk));

  return (
    <div className="chart" role="img" aria-label="Projected net worth and liquid share by year">
      {points.map((point) => {
        const netWorthHeight = `${Math.round((point.netWorthDkk / maxNetWorth) * 100)}%`;
        const liquidHeight = `${Math.round(liquidityShare(point) * 100)}%`;

        return (
          <div className="chartColumn" key={point.year}>
            <div className="barTrack">
              <div className="bar netWorthBar" style={{ height: netWorthHeight }} />
              <div className="bar liquidityBar" style={{ height: liquidHeight }} />
            </div>
            <span>{point.year}</span>
          </div>
        );
      })}
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

export default App;
