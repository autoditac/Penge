/** Imports: guided wizard over the staged import-sessions API (#207/#208).
 *
 * Flow: upload (drop zone or picker) → review staged rows (badges, inline
 * edits, exclusions) → commit → summary; plus an import-history list with
 * resume for staged sessions. In demo mode the flow runs against the
 * deterministic in-memory store in `demo/importsStore.ts`.
 */

import { useReducer, useState } from "react";
import { Link } from "react-router";

import {
  useCommitImport,
  useDiscardImport,
  useImportSession,
  useImportSessions,
  usePatchImportRow,
  useUploadImport,
} from "../api/queries";
import type { ImportRow, ImportSessionWithRows } from "../api/schemas";
import { ErrorState, LoadingState } from "../components/primitives";
import { initialWizardState, wizardReducer } from "../imports/machine";
import type { WizardEvent, WizardState } from "../imports/machine";
import {
  applyEdits,
  canCommit,
  editableFields,
  formatTimestamp,
  rowBadge,
  SOURCE_LABELS,
  shortSha,
  sourceLabel,
  summarizeIssues,
} from "../imports/transforms";

const SOURCE_OPTIONS = Object.entries(SOURCE_LABELS);

export function ImportsPage(): React.JSX.Element {
  const [wizard, dispatch] = useReducer(wizardReducer, initialWizardState);

  return (
    <>
      <section className="pageIntro">
        <h1>Imports</h1>
        <p>
          Upload a statement export, review every staged row, fix or exclude what does not belong,
          and only then commit. Nothing is written to the warehouse before the confirm step.
        </p>
      </section>
      <WizardSteps state={wizard} />
      {wizard.step === "upload" && <UploadPanel state={wizard} dispatch={dispatch} />}
      {wizard.step === "review" && (
        <ReviewPanel sessionId={wizard.sessionId} state={wizard} dispatch={dispatch} />
      )}
      {wizard.step === "done" && <DonePanel state={wizard} dispatch={dispatch} />}
      <HistoryPanel
        dispatch={dispatch}
        activeSessionId={wizard.step === "review" ? wizard.sessionId : null}
      />
    </>
  );
}

/* ---- step indicator ---- */

const STEP_ORDER = ["upload", "review", "done"] as const;
const STEP_TITLES: Record<(typeof STEP_ORDER)[number], string> = {
  upload: "1 · Upload",
  review: "2 · Review",
  done: "3 · Done",
};

function WizardSteps({ state }: { readonly state: WizardState }): React.JSX.Element {
  const activeIndex = STEP_ORDER.indexOf(state.step);
  return (
    <nav className="wizardSteps" aria-label="Import wizard progress">
      {STEP_ORDER.map((step, index) => (
        <span
          key={step}
          className={
            index === activeIndex
              ? "wizardStep wizardStepActive"
              : index < activeIndex
                ? "wizardStep wizardStepDone"
                : "wizardStep"
          }
          aria-current={index === activeIndex ? "step" : undefined}
        >
          {STEP_TITLES[step]}
        </span>
      ))}
    </nav>
  );
}

/* ---- step 1: upload ---- */

type StepProps = {
  readonly state: WizardState;
  readonly dispatch: React.Dispatch<WizardEvent>;
};

function UploadPanel({ state, dispatch }: StepProps): React.JSX.Element {
  const upload = useUploadImport();
  const [source, setSource] = useState("");
  const [entityName, setEntityName] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const busy = state.step === "upload" && state.busy;

  const startUpload = (file: File): void => {
    dispatch({ type: "UPLOAD_STARTED" });
    upload.mutate(
      { file, options: { source: source || undefined, entityName: entityName || undefined } },
      {
        onSuccess: (session) => {
          dispatch({ type: "UPLOAD_SUCCEEDED", sessionId: session.id });
        },
        onError: (error) => {
          dispatch({ type: "UPLOAD_FAILED", message: error.message });
        },
      },
    );
  };

  const onFileChange = (event: React.ChangeEvent<HTMLInputElement>): void => {
    const file = event.target.files?.[0];
    if (file !== undefined && !busy) {
      startUpload(file);
    }
    event.target.value = "";
  };

  const onDrop = (event: React.DragEvent): void => {
    event.preventDefault();
    setDragOver(false);
    const file = event.dataTransfer.files[0];
    if (file !== undefined && !busy) {
      startUpload(file);
    }
  };

  return (
    <section className="panel">
      <div className="panelHeader">
        <div>
          <p className="eyebrow">Step 1</p>
          <h2>Upload a statement export</h2>
        </div>
        <span className="pill">staged, not written</span>
      </div>
      <div className="wizardControls">
        <label className="fieldLabel" htmlFor="import-source">
          Source (auto-detected when left blank)
          <select
            id="import-source"
            value={source}
            onChange={(event) => {
              setSource(event.target.value);
            }}
          >
            <option value="">Auto-detect</option>
            {SOURCE_OPTIONS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="fieldLabel" htmlFor="import-entity">
          Entity name (required for Growney/PFA commits)
          <input
            id="import-entity"
            type="text"
            value={entityName}
            placeholder="e.g. Person A"
            onChange={(event) => {
              setEntityName(event.target.value);
            }}
          />
        </label>
      </div>
      <label
        className={dragOver ? "dropZone dropZoneActive" : "dropZone"}
        htmlFor="import-file"
        onDragOver={(event) => {
          event.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => {
          setDragOver(false);
        }}
        onDrop={onDrop}
      >
        <strong>{busy ? "Uploading…" : "Drop a file here or browse"}</strong>
        <span className="stateHint">
          Nordnet CSV · Growney/PFA PDF · manual balances JSON — max 25 MiB
        </span>
        <input
          id="import-file"
          type="file"
          accept=".csv,.pdf,.json"
          onChange={onFileChange}
          disabled={busy}
        />
      </label>
      {state.step === "upload" && state.error !== null && (
        <div className="stateBox stateError" role="alert">
          <strong>Upload failed</strong>
          <p className="stateDetail">{state.error}</p>
        </div>
      )}
    </section>
  );
}

/* ---- step 2: review ---- */

type ReviewPanelProps = StepProps & {
  readonly sessionId: string;
};

function ReviewPanel({ sessionId, state, dispatch }: ReviewPanelProps): React.JSX.Element {
  const sessionQuery = useImportSession(sessionId);
  const commit = useCommitImport();
  const discard = useDiscardImport();
  const [entityName, setEntityName] = useState("");

  if (sessionQuery.isPending) {
    return (
      <section className="panel">
        <LoadingState label="staged session" />
      </section>
    );
  }
  if (sessionQuery.isError) {
    return (
      <section className="panel">
        <ErrorState label="staged session" error={sessionQuery.error} />
      </section>
    );
  }

  const session = sessionQuery.data;
  const committing = state.step === "review" && state.busy;
  const discarding = discard.isPending;
  const busy = committing || discarding;
  const needsEntityName =
    (session.source === "growney" || session.source === "pfa") &&
    typeof session.params["entity_name"] !== "string";
  const committable = canCommit(session.rows) && !(needsEntityName && entityName === "");

  const onCommit = (): void => {
    dispatch({ type: "COMMIT_STARTED" });
    commit.mutate(
      { sessionId, options: { entityName: entityName || undefined } },
      {
        onSuccess: (response) => {
          dispatch({ type: "COMMIT_SUCCEEDED", counts: response.counts });
        },
        onError: (error) => {
          dispatch({ type: "COMMIT_FAILED", message: error.message });
        },
      },
    );
  };

  const onDiscard = (): void => {
    discard.mutate(sessionId, {
      onSuccess: () => {
        dispatch({ type: "DISCARD_SUCCEEDED" });
      },
      onError: (error) => {
        dispatch({ type: "COMMIT_FAILED", message: error.message });
      },
    });
  };

  return (
    <section className="panel">
      <div className="panelHeader">
        <div>
          <p className="eyebrow">Step 2 · {sourceLabel(session.source)}</p>
          <h2>{session.original_filename}</h2>
        </div>
        <span className="pill mono" title={session.content_sha256}>
          sha256 {shortSha(session.content_sha256)}
        </span>
      </div>
      <RowCountsBar session={session} />
      <RowsTable session={session} />
      {state.step === "review" && state.error !== null && (
        <div className="stateBox stateError" role="alert">
          <strong>Action failed</strong>
          <p className="stateDetail">{state.error}</p>
        </div>
      )}
      <div className="wizardActions">
        {needsEntityName && (
          <label className="fieldLabel" htmlFor="commit-entity">
            Entity name
            <input
              id="commit-entity"
              type="text"
              value={entityName}
              placeholder="e.g. Person A"
              onChange={(event) => {
                setEntityName(event.target.value);
              }}
            />
          </label>
        )}
        <button
          type="button"
          className="buttonPrimary"
          onClick={onCommit}
          disabled={busy || !committable}
        >
          {committing
            ? "Committing…"
            : `Commit ${String(session.row_counts.total - session.row_counts.excluded)} rows`}
        </button>
        <button type="button" className="buttonGhost" onClick={onDiscard} disabled={busy}>
          {discarding ? "Discarding…" : "Discard session"}
        </button>
        <button
          type="button"
          className="buttonGhost"
          onClick={() => {
            dispatch({ type: "RESET" });
          }}
          disabled={busy}
        >
          Back to upload
        </button>
      </div>
      {!canCommit(session.rows) && (
        <p className="supporting">Fix or exclude the error rows before committing.</p>
      )}
    </section>
  );
}

function RowCountsBar({ session }: { readonly session: ImportSessionWithRows }): React.JSX.Element {
  const counts = session.row_counts;
  return (
    <div className="rowCounts" aria-label="Row validation summary">
      <span className="badge tone-good">{counts.ok} ok</span>
      <span className="badge tone-watch">{counts.warning} duplicates</span>
      <span className="badge tone-critical">{counts.error} errors</span>
      <span className="badge tone-info">{counts.excluded} excluded</span>
    </div>
  );
}

function RowsTable({ session }: { readonly session: ImportSessionWithRows }): React.JSX.Element {
  const [editingRowId, setEditingRowId] = useState<string | null>(null);

  return (
    <table className="dataTable">
      <thead>
        <tr>
          <th scope="col">#</th>
          <th scope="col">Kind</th>
          <th scope="col">Status</th>
          <th scope="col">Summary</th>
          <th scope="col">Actions</th>
        </tr>
      </thead>
      <tbody>
        {session.rows.map((row) => (
          <RowEntry
            key={row.id}
            sessionId={session.id}
            row={row}
            sessionStaged={session.status === "staged"}
            editing={editingRowId === row.id}
            onEditToggle={(open) => {
              setEditingRowId(open ? row.id : null);
            }}
          />
        ))}
      </tbody>
    </table>
  );
}

function rowSummary(row: ImportRow): string {
  const issueText = summarizeIssues(row.issues);
  if (issueText !== "") {
    return issueText;
  }
  return editableFields(row.payload)
    .slice(0, 4)
    .map((field) => `${field.key}: ${field.value}`)
    .join(" · ");
}

type RowEntryProps = {
  readonly sessionId: string;
  readonly row: ImportRow;
  readonly sessionStaged: boolean;
  readonly editing: boolean;
  readonly onEditToggle: (open: boolean) => void;
};

function RowEntry({
  sessionId,
  row,
  sessionStaged,
  editing,
  onEditToggle,
}: RowEntryProps): React.JSX.Element {
  const patch = usePatchImportRow();
  const badge = rowBadge(row);

  const toggleExcluded = (): void => {
    patch.mutate({ sessionId, rowId: row.id, patch: { excluded: !row.excluded } });
  };

  return (
    <>
      <tr className={row.excluded ? "rowExcluded" : undefined}>
        <td className="num">{row.row_index}</td>
        <td>{row.kind}</td>
        <td>
          <span className={`badge tone-${badge.tone}`}>{badge.label}</span>
          {row.edited && <span className="badge tone-info">edited</span>}
        </td>
        <td className="rowSummary">{rowSummary(row)}</td>
        <td className="rowActions">
          {sessionStaged && (
            <>
              <button
                type="button"
                className="buttonGhost"
                onClick={() => {
                  onEditToggle(!editing);
                }}
                disabled={patch.isPending}
              >
                {editing ? "Close" : "Edit"}
              </button>
              <button
                type="button"
                className="buttonGhost"
                onClick={toggleExcluded}
                disabled={patch.isPending}
              >
                {row.excluded ? "Include" : "Exclude"}
              </button>
            </>
          )}
        </td>
      </tr>
      {editing && sessionStaged && (
        <tr>
          <td colSpan={5}>
            <RowEditor
              row={row}
              pending={patch.isPending}
              onSave={(edits) => {
                patch.mutate(
                  { sessionId, rowId: row.id, patch: { payload: applyEdits(row.payload, edits) } },
                  {
                    onSuccess: () => {
                      onEditToggle(false);
                    },
                  },
                );
              }}
              onCancel={() => {
                onEditToggle(false);
              }}
            />
          </td>
        </tr>
      )}
    </>
  );
}

type RowEditorProps = {
  readonly row: ImportRow;
  readonly pending: boolean;
  readonly onSave: (edits: Record<string, string>) => void;
  readonly onCancel: () => void;
};

function RowEditor({ row, pending, onSave, onCancel }: RowEditorProps): React.JSX.Element {
  const fields = editableFields(row.payload);
  const [draft, setDraft] = useState<Record<string, string>>(() =>
    Object.fromEntries(fields.map((field) => [field.key, field.value])),
  );

  return (
    <form
      className="rowEditor"
      onSubmit={(event) => {
        event.preventDefault();
        onSave(draft);
      }}
    >
      {fields.map((field) => (
        <label key={field.key} className="fieldLabel" htmlFor={`edit-${row.id}-${field.key}`}>
          {field.key}
          <input
            id={`edit-${row.id}-${field.key}`}
            type="text"
            value={draft[field.key] ?? ""}
            onChange={(event) => {
              setDraft((prev) => ({ ...prev, [field.key]: event.target.value }));
            }}
          />
        </label>
      ))}
      <div className="wizardActions">
        <button type="submit" className="buttonPrimary" disabled={pending}>
          {pending ? "Saving…" : "Save row"}
        </button>
        <button type="button" className="buttonGhost" onClick={onCancel} disabled={pending}>
          Cancel
        </button>
      </div>
    </form>
  );
}

/* ---- step 3: done ---- */

function DonePanel({ state, dispatch }: StepProps): React.JSX.Element {
  if (state.step !== "done") {
    return <></>;
  }
  const counts = state.counts;
  return (
    <section className="panel">
      <div className="panelHeader">
        <div>
          <p className="eyebrow">Step 3</p>
          <h2>Import committed</h2>
        </div>
        <span className="pill">written via connector loaders</span>
      </div>
      <div className="rowCounts">
        <span className="badge tone-good">{counts.transactions} transactions</span>
        <span className="badge tone-good">{counts.holding_snapshots} holding snapshots</span>
        <span className="badge tone-info">{counts.accounts} accounts</span>
        <span className="badge tone-info">{counts.entities} entities</span>
        <span className="badge tone-info">{counts.instruments} instruments</span>
      </div>
      <p className="supporting">
        Rebuild the marts (<code>dbt build</code>) to refresh the dashboards, then check the
        affected accounts on the <Link to="/">overview</Link>.
      </p>
      <div className="wizardActions">
        <button
          type="button"
          className="buttonPrimary"
          onClick={() => {
            dispatch({ type: "RESET" });
          }}
        >
          Import another file
        </button>
      </div>
    </section>
  );
}

/* ---- history ---- */

type HistoryPanelProps = {
  readonly dispatch: React.Dispatch<WizardEvent>;
  readonly activeSessionId: string | null;
};

function HistoryPanel({ dispatch, activeSessionId }: HistoryPanelProps): React.JSX.Element {
  const sessions = useImportSessions();

  return (
    <section className="panel">
      <div className="panelHeader">
        <div>
          <p className="eyebrow">History</p>
          <h2>Past import sessions</h2>
        </div>
        <span className="pill">{sessions.data?.total ?? 0} sessions</span>
      </div>
      {sessions.isPending && <LoadingState label="import history" />}
      {sessions.isError && <ErrorState label="import history" error={sessions.error} />}
      {sessions.data !== undefined && sessions.data.sessions.length === 0 && (
        <p className="supporting">No imports yet — upload the first statement above.</p>
      )}
      {sessions.data !== undefined && sessions.data.sessions.length > 0 && (
        <table className="dataTable">
          <thead>
            <tr>
              <th scope="col">File</th>
              <th scope="col">Source</th>
              <th scope="col">Status</th>
              <th scope="col">Rows</th>
              <th scope="col">Created</th>
              <th scope="col">Actions</th>
            </tr>
          </thead>
          <tbody>
            {sessions.data.sessions.map((session) => (
              <tr key={session.id}>
                <td className="rowSummary">{session.original_filename}</td>
                <td>{sourceLabel(session.source)}</td>
                <td>
                  <span className={`badge tone-${statusTone(session.status)}`}>
                    {session.status}
                  </span>
                </td>
                <td className="num">
                  {session.row_counts.ok}/{session.row_counts.total} ok
                  {session.row_counts.error > 0 && ` · ${String(session.row_counts.error)} errors`}
                </td>
                <td>{formatTimestamp(session.created_at)}</td>
                <td className="rowActions">
                  {session.status === "staged" && session.id !== activeSessionId && (
                    <button
                      type="button"
                      className="buttonGhost"
                      onClick={() => {
                        dispatch({ type: "RESUME_SESSION", sessionId: session.id });
                      }}
                    >
                      Resume
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function statusTone(status: string): string {
  switch (status) {
    case "staged":
      return "watch";
    case "committed":
      return "good";
    case "discarded":
      return "info";
    case "expired":
      return "critical";
    default:
      return "info";
  }
}
