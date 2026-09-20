/** Component tests for the toast notification system (issue #271
 * acceptance: reusable notifications for background actions).
 * @vitest-environment jsdom
 */
import { ThemeProvider } from "@mui/material/styles";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { NotificationsProvider, useNotify } from "../src/components/Notifications";
import { buildMuiTheme } from "../src/theme/muiTheme";

function TriggerButton({
  message,
  severity,
}: {
  readonly message: string;
  readonly severity?: "success" | "error" | "info" | "warning";
}): React.JSX.Element {
  const notify = useNotify();
  return (
    <button
      type="button"
      onClick={() => {
        notify(message, severity);
      }}
    >
      fire
    </button>
  );
}

/** Fires two distinct messages from a single click, so a test can queue
 * both notifications up front without an intervening clickaway dismissing
 * the first toast early (clicking elsewhere on the page while a toast is
 * open dismisses it via MUI's Snackbar clickaway handling). */
function TwoTriggerButtons({
  firstMessage,
  secondMessage,
}: {
  readonly firstMessage: string;
  readonly secondMessage: string;
}): React.JSX.Element {
  const notify = useNotify();
  return (
    <button
      type="button"
      onClick={() => {
        notify(firstMessage);
        notify(secondMessage);
      }}
    >
      fire both
    </button>
  );
}

function renderWithProvider(ui: React.ReactElement): ReturnType<typeof render> {
  return render(
    <ThemeProvider theme={buildMuiTheme("dark")}>
      <NotificationsProvider>{ui}</NotificationsProvider>
    </ThemeProvider>,
  );
}

describe("NotificationsProvider / useNotify", () => {
  it("shows a toast with the given message and severity when notify is called", async () => {
    const user = userEvent.setup();
    renderWithProvider(<TriggerButton message="Committed 3 transactions." severity="success" />);
    expect(screen.queryByText("Committed 3 transactions.")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "fire" }));

    await waitFor(() => {
      expect(screen.getByText("Committed 3 transactions.")).toBeInTheDocument();
    });
    expect(screen.getByRole("alert")).toHaveClass("MuiAlert-colorSuccess", "MuiAlert-filled");
  });

  it("advances the queue: dismissing the first toast reveals the second", async () => {
    const user = userEvent.setup();
    renderWithProvider(<TwoTriggerButtons firstMessage="first" secondMessage="second" />);

    // Queue both notifications before dismissing either, so the second one
    // is waiting behind the first when it closes.
    await user.click(screen.getByRole("button", { name: "fire both" }));
    await waitFor(() => {
      expect(screen.getByText("first")).toBeInTheDocument();
    });
    expect(screen.queryByText("second")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /close/i }));

    await waitFor(() => {
      expect(screen.queryByText("first")).not.toBeInTheDocument();
      expect(screen.getByText("second")).toBeInTheDocument();
    });
  });

  it("throws when useNotify is used outside a NotificationsProvider", () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    expect(() => render(<TriggerButton message="x" />)).toThrow(
      "useNotify must be used within a NotificationsProvider",
    );
    consoleError.mockRestore();
  });
});
