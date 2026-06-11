/** Shared presentational building blocks: EUR/DKK pairs, states, KPI cards. */

import { formatMoney } from "../money";
import type { Currency } from "../money";

type MoneyPairProps = {
  readonly eur: number | null;
  readonly dkk: number | null;
  readonly primary?: Currency;
};

/** EUR and DKK shown in parallel — never one silently picked as base (ADR-0004). */
export function MoneyPair({ eur, dkk, primary = "DKK" }: MoneyPairProps): React.JSX.Element {
  const [first, second]: readonly [
    readonly [number | null, Currency],
    readonly [number | null, Currency],
  ] =
    primary === "DKK"
      ? ([
          [dkk, "DKK"],
          [eur, "EUR"],
        ] as const)
      : ([
          [eur, "EUR"],
          [dkk, "DKK"],
        ] as const);

  return (
    <span className="moneyPair">
      <strong>{formatMoney(first[0], first[1])}</strong>
      <small>{formatMoney(second[0], second[1])}</small>
    </span>
  );
}

type KpiCardProps = {
  readonly label: string;
  readonly children: React.ReactNode;
  readonly detail?: string;
  readonly tone?: "good" | "watch" | "critical" | "info";
};

export function KpiCard({
  label,
  children,
  detail,
  tone = "info",
}: KpiCardProps): React.JSX.Element {
  return (
    <article className={`kpiCard tone-${tone}`}>
      <span className="kpiLabel">{label}</span>
      <div className="kpiValue">{children}</div>
      {detail !== undefined ? <small className="kpiDetail">{detail}</small> : null}
    </article>
  );
}

export function LoadingState({ label }: { readonly label: string }): React.JSX.Element {
  return (
    <div className="stateBox" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <p>Loading {label}…</p>
    </div>
  );
}

type ErrorStateProps = {
  readonly label: string;
  readonly error: Error;
  readonly onRetry?: () => void;
};

export function ErrorState({ label, error, onRetry }: ErrorStateProps): React.JSX.Element {
  return (
    <div className="stateBox stateError" role="alert">
      <p>
        <strong>Could not load {label}.</strong>
      </p>
      <p className="stateDetail">{error.message}</p>
      <p className="stateHint">
        Start the read API with <code>just api-dev</code>, or set <code>VITE_PENGE_DEMO=true</code>{" "}
        for synthetic demo data.
      </p>
      {onRetry !== undefined ? (
        <button type="button" onClick={onRetry}>
          Retry
        </button>
      ) : null}
    </div>
  );
}

export function EmptyState({ label }: { readonly label: string }): React.JSX.Element {
  return (
    <div className="stateBox">
      <p>No {label} available yet. Run an ingest + dbt build to populate the marts.</p>
    </div>
  );
}
