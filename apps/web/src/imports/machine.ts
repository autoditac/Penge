/** Import wizard state machine (pure, tested).
 *
 * The wizard is a small explicit state machine instead of scattered
 * `useState` flags so transitions can be unit-tested and illegal moves
 * (e.g. committing before a session exists) are unrepresentable.
 */

import type { CommitCounts } from "../api/schemas";

export type WizardState =
  | { readonly step: "upload"; readonly busy: boolean; readonly error: string | null }
  | {
      readonly step: "review";
      readonly sessionId: string;
      readonly busy: boolean;
      readonly error: string | null;
    }
  | {
      readonly step: "done";
      readonly sessionId: string;
      readonly counts: CommitCounts;
    };

export type WizardEvent =
  | { readonly type: "UPLOAD_STARTED" }
  | { readonly type: "UPLOAD_SUCCEEDED"; readonly sessionId: string }
  | { readonly type: "UPLOAD_FAILED"; readonly message: string }
  | { readonly type: "RESUME_SESSION"; readonly sessionId: string }
  | { readonly type: "COMMIT_STARTED" }
  | { readonly type: "COMMIT_SUCCEEDED"; readonly counts: CommitCounts }
  | { readonly type: "COMMIT_FAILED"; readonly message: string }
  | { readonly type: "DISCARD_SUCCEEDED" }
  | { readonly type: "RESET" };

export const initialWizardState: WizardState = { step: "upload", busy: false, error: null };

export function wizardReducer(state: WizardState, event: WizardEvent): WizardState {
  switch (event.type) {
    case "UPLOAD_STARTED":
      if (state.step !== "upload") {
        return state;
      }
      return { step: "upload", busy: true, error: null };
    case "UPLOAD_SUCCEEDED":
      if (state.step !== "upload") {
        return state;
      }
      return { step: "review", sessionId: event.sessionId, busy: false, error: null };
    case "UPLOAD_FAILED":
      if (state.step !== "upload") {
        return state;
      }
      return { step: "upload", busy: false, error: event.message };
    case "RESUME_SESSION":
      // Resuming from history is allowed from any non-busy state.
      if (state.step !== "done" && state.busy) {
        return state;
      }
      return { step: "review", sessionId: event.sessionId, busy: false, error: null };
    case "COMMIT_STARTED":
      if (state.step !== "review") {
        return state;
      }
      return { ...state, busy: true, error: null };
    case "COMMIT_SUCCEEDED":
      if (state.step !== "review") {
        return state;
      }
      return { step: "done", sessionId: state.sessionId, counts: event.counts };
    case "COMMIT_FAILED":
      if (state.step !== "review") {
        return state;
      }
      return { ...state, busy: false, error: event.message };
    case "DISCARD_SUCCEEDED":
      if (state.step !== "review") {
        return state;
      }
      return initialWizardState;
    case "RESET":
      return initialWizardState;
  }
}
