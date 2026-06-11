/** Imports: roadmap surface until the import-sessions API (#207) and the
 * guided wizard (#208) land. Documents today's CLI-based flow. */

export function ImportsPage(): React.JSX.Element {
  return (
    <>
      <section className="pageIntro">
        <h1>Imports</h1>
        <p>
          The guided import assistant is on the roadmap: a wizard with upload, parser preview,
          AI-suggested mappings via MCP, and human approval before anything is written.
        </p>
      </section>
      <section className="panel">
        <div className="panelHeader">
          <div>
            <p className="eyebrow">Current flow</p>
            <h2>Importing statements today</h2>
          </div>
          <span className="pill">CLI</span>
        </div>
        <ol className="stepList">
          <li>
            Drop the exported CSV/PDF into the local inbox — never commit statements to the repo.
          </li>
          <li>
            Run the matching connector, e.g. <code>just ingest-gls</code> or{" "}
            <code>penge-nordnet</code> (see the monthly-ritual runbook).
          </li>
          <li>
            Rebuild marts with <code>dbt build</code>; the dashboards refresh on reload.
          </li>
        </ol>
      </section>
      <section className="panel">
        <div className="panelHeader">
          <div>
            <p className="eyebrow">Planned</p>
            <h2>Guided wizard</h2>
          </div>
          <span className="pill">#207 · #208</span>
        </div>
        <ul className="stepList">
          <li>Upload &amp; staging with parser auto-detection and a dry-run preview.</li>
          <li>
            AI mapping suggestions through the sanctioned MCP boundary — aggregates only, with human
            approval gates.
          </li>
          <li>Idempotent commit into the warehouse with full audit trail.</li>
        </ul>
      </section>
    </>
  );
}
