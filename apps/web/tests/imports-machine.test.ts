import { describe, expect, it } from "vitest";

import { initialWizardState, wizardReducer } from "../src/imports/machine";
import type { WizardState } from "../src/imports/machine";

const counts = {
  entities: 1,
  accounts: 1,
  instruments: 0,
  transactions: 2,
  holding_snapshots: 0,
};

describe("wizardReducer", () => {
  it("walks the happy path upload → review → done", () => {
    let state: WizardState = initialWizardState;
    state = wizardReducer(state, { type: "UPLOAD_STARTED" });
    expect(state).toEqual({ step: "upload", busy: true, error: null });

    state = wizardReducer(state, { type: "UPLOAD_SUCCEEDED", sessionId: "s1" });
    expect(state).toEqual({ step: "review", sessionId: "s1", busy: false, error: null });

    state = wizardReducer(state, { type: "COMMIT_STARTED" });
    expect(state).toEqual({ step: "review", sessionId: "s1", busy: true, error: null });

    state = wizardReducer(state, { type: "COMMIT_SUCCEEDED", counts });
    expect(state).toEqual({ step: "done", sessionId: "s1", counts });
  });

  it("records upload failures and clears them on retry", () => {
    let state: WizardState = wizardReducer(initialWizardState, { type: "UPLOAD_STARTED" });
    state = wizardReducer(state, { type: "UPLOAD_FAILED", message: "could not detect source" });
    expect(state).toEqual({ step: "upload", busy: false, error: "could not detect source" });

    state = wizardReducer(state, { type: "UPLOAD_STARTED" });
    expect(state).toEqual({ step: "upload", busy: true, error: null });
  });

  it("keeps the session on commit failure so rows can be fixed", () => {
    let state: WizardState = { step: "review", sessionId: "s1", busy: true, error: null };
    state = wizardReducer(state, { type: "COMMIT_FAILED", message: "fix error rows" });
    expect(state).toEqual({
      step: "review",
      sessionId: "s1",
      busy: false,
      error: "fix error rows",
    });
  });

  it("returns to upload after a discard", () => {
    const state = wizardReducer(
      { step: "review", sessionId: "s1", busy: false, error: null },
      { type: "DISCARD_SUCCEEDED" },
    );
    expect(state).toEqual(initialWizardState);
  });

  it("resumes a session from history", () => {
    const state = wizardReducer(initialWizardState, { type: "RESUME_SESSION", sessionId: "s9" });
    expect(state).toEqual({ step: "review", sessionId: "s9", busy: false, error: null });
  });

  it("allows resuming another session from the done step", () => {
    const state = wizardReducer(
      { step: "done", sessionId: "s1", counts },
      { type: "RESUME_SESSION", sessionId: "s2" },
    );
    expect(state).toEqual({ step: "review", sessionId: "s2", busy: false, error: null });
  });

  it("ignores resume while an action is in flight", () => {
    const busyState: WizardState = { step: "review", sessionId: "s1", busy: true, error: null };
    expect(wizardReducer(busyState, { type: "RESUME_SESSION", sessionId: "s2" })).toBe(busyState);
  });

  it("ignores commit events outside the review step", () => {
    expect(wizardReducer(initialWizardState, { type: "COMMIT_STARTED" })).toBe(initialWizardState);
    expect(wizardReducer(initialWizardState, { type: "COMMIT_SUCCEEDED", counts })).toBe(
      initialWizardState,
    );
  });

  it("ignores upload events outside the upload step", () => {
    const review: WizardState = { step: "review", sessionId: "s1", busy: false, error: null };
    expect(wizardReducer(review, { type: "UPLOAD_STARTED" })).toBe(review);
    expect(wizardReducer(review, { type: "UPLOAD_FAILED", message: "x" })).toBe(review);
  });

  it("resets from any state", () => {
    expect(wizardReducer({ step: "done", sessionId: "s1", counts }, { type: "RESET" })).toEqual(
      initialWizardState,
    );
    expect(
      wizardReducer(
        { step: "review", sessionId: "s1", busy: true, error: null },
        { type: "RESET" },
      ),
    ).toEqual(initialWizardState);
  });
});
