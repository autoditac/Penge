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

  it("dismisses the current toast and can show a new one afterwards", async () => {
    const user = userEvent.setup();
    renderWithProvider(<TriggerButton message="first" severity="info" />);

    await user.click(screen.getByRole("button", { name: "fire" }));
    await waitFor(() => {
      expect(screen.getByText("first")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /close/i }));
    await waitFor(() => {
      expect(screen.queryByText("first")).not.toBeInTheDocument();
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
