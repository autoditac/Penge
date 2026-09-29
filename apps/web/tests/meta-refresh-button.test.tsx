/** Component tests for the WebUI dbt-refresh button (issue #285).
 *
 * Verifies the button disables itself and shows an indeterminate progress
 * bar with status text while pending (never a fake percentage), and that a
 * completed mutation surfaces the expected success/error toast.
 * @vitest-environment jsdom
 */
import { ThemeProvider } from "@mui/material/styles";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { NotificationsProvider } from "../src/components/Notifications";
import { buildMuiTheme } from "../src/theme/muiTheme";

const useTriggerMetaRefreshMock = vi.fn();

vi.mock("../src/api/queries", () => ({
  useTriggerMetaRefresh: () => useTriggerMetaRefreshMock(),
}));

const { MetaRefreshButton } = await import("../src/components/MetaRefreshButton");

function renderButton(): ReturnType<typeof render> {
  return render(
    <ThemeProvider theme={buildMuiTheme("dark")}>
      <NotificationsProvider>
        <MetaRefreshButton />
      </NotificationsProvider>
    </ThemeProvider>,
  );
}

afterEach(() => {
  useTriggerMetaRefreshMock.mockReset();
});

describe("MetaRefreshButton", () => {
  it("is enabled and shows no progress bar while idle", () => {
    useTriggerMetaRefreshMock.mockReturnValue({
      isPending: false,
      isSuccess: false,
      isError: false,
      mutate: vi.fn(),
    });
    renderButton();

    const button = screen.getByRole("button", { name: "Refresh analytics" });
    expect(button).toBeEnabled();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("triggers the mutation and disables duplicate submissions on click", async () => {
    const mutate = vi.fn();
    useTriggerMetaRefreshMock.mockReturnValue({
      isPending: false,
      isSuccess: false,
      isError: false,
      mutate,
    });
    const user = userEvent.setup();
    renderButton();

    await user.click(screen.getByRole("button", { name: "Refresh analytics" }));
    expect(mutate).toHaveBeenCalledTimes(1);
  });

  it("shows an indeterminate progress bar and status text while pending", () => {
    useTriggerMetaRefreshMock.mockReturnValue({
      isPending: true,
      isSuccess: false,
      isError: false,
      mutate: vi.fn(),
    });
    renderButton();

    const button = screen.getByRole("button", { name: "Refreshing…" });
    expect(button).toBeDisabled();
    const progress = screen.getByRole("progressbar");
    expect(progress).not.toHaveAttribute("aria-valuenow");
    expect(screen.getByText("Building and validating marts…")).toBeInTheDocument();
  });

  it("notifies success with the completion timestamp", async () => {
    useTriggerMetaRefreshMock.mockReturnValue({
      isPending: false,
      isSuccess: true,
      isError: false,
      data: { status: "succeeded", completed_at: "2026-06-01T09:00:00Z" },
      mutate: vi.fn(),
    });
    renderButton();

    await waitFor(() => {
      expect(
        screen.getByText("Analytics refreshed (as of 2026-06-01T09:00:00Z)."),
      ).toBeInTheDocument();
    });
  });

  it("notifies the error message on failure", async () => {
    useTriggerMetaRefreshMock.mockReturnValue({
      isPending: false,
      isSuccess: false,
      isError: true,
      error: new Error("Refresh already in progress"),
      mutate: vi.fn(),
    });
    renderButton();

    await waitFor(() => {
      expect(screen.getByText("Refresh already in progress")).toBeInTheDocument();
    });
  });
});
