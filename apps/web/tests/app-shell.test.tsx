/** Component tests for the responsive AppShell navigation (issue #271).
 * @vitest-environment jsdom
 */
import { ThemeProvider } from "@mui/material/styles";
import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ThemeModeContext } from "../src/theme";
import { buildMuiTheme } from "../src/theme/muiTheme";

const useFreshnessMock = vi.fn();
const useTriggerMetaRefreshMock = vi.fn();
const notifyMock = vi.fn();

vi.mock("../src/api/queries", () => ({
  useFreshness: () => useFreshnessMock(),
  useTriggerMetaRefresh: () => useTriggerMetaRefreshMock(),
}));

vi.mock("../src/components/Notifications", () => ({
  useNotify: () => notifyMock,
}));

const useMediaQueryMock = vi.fn();

vi.mock("@mui/material/useMediaQuery", () => ({
  default: () => useMediaQueryMock(),
}));

// Imported after the mocks above so AppShell picks up the mocked modules.
const { AppShell } = await import("../src/shell/AppShell");

function renderShell(): ReturnType<typeof render> {
  const router = createMemoryRouter(
    [{ path: "/", Component: AppShell, children: [{ index: true, element: <p>page body</p> }] }],
    { initialEntries: ["/"] },
  );
  return render(
    <ThemeModeContext.Provider value={{ theme: "dark", toggleTheme: vi.fn() }}>
      <ThemeProvider theme={buildMuiTheme("dark")}>
        <RouterProvider router={router} />
      </ThemeProvider>
    </ThemeModeContext.Provider>,
  );
}

describe("AppShell", () => {
  beforeEach(() => {
    useFreshnessMock.mockReturnValue({
      isPending: false,
      isError: false,
      data: { marts: [{ latest_as_of: "2024-01-01" }] },
    });
    useTriggerMetaRefreshMock.mockReturnValue({
      isPending: false,
      isSuccess: false,
      isError: false,
      mutate: vi.fn(),
    });
  });

  afterEach(() => {
    useFreshnessMock.mockReset();
    useTriggerMetaRefreshMock.mockReset();
    notifyMock.mockReset();
    useMediaQueryMock.mockReset();
  });

  it("renders a permanent primary navigation drawer on desktop", () => {
    useMediaQueryMock.mockReturnValue(true);
    renderShell();
    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(nav).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Overview/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Performance/ })).toBeInTheDocument();
    expect(screen.getByText("page body")).toBeInTheDocument();
  });

  it("renders a compact top bar and bottom navigation on mobile", () => {
    useMediaQueryMock.mockReturnValue(false);
    renderShell();
    expect(screen.queryByRole("navigation", { name: "Primary" })).not.toBeInTheDocument();
    const links = screen.getAllByRole("link", {
      name: /Overview|Performance|Imports|Connections|Planning/,
    });
    expect(links.length).toBeGreaterThanOrEqual(5);
    expect(screen.getByText("page body")).toBeInTheDocument();
  });

  it("marks the active route link for accessibility and styling", () => {
    useMediaQueryMock.mockReturnValue(true);
    renderShell();
    const overviewLink = screen.getByRole("link", { name: /Overview/ });
    expect(overviewLink).toHaveAttribute("aria-current", "page");
  });
});
