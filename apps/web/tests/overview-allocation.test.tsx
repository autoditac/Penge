/** Allocation donut: distinct colours and table-as-legend.
 * @vitest-environment jsdom
 */
import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ThemeModeContext } from "../src/theme";
import { paletteTokens } from "../src/theme/tokens";
import type { ThemeMode } from "../src/theme/tokens";
import { allocationSlices } from "../src/transforms";
import { renderWithTheme } from "./test-utils";

// ECharts needs a real canvas; the chart itself is not under test here.
vi.mock("../src/api/queries", () => ({
  useAllocation: () => ({
    isPending: false,
    isError: false,
    data: {
      as_of: "2026-09-28",
      by: "kind",
      slices: [
        { label: "real_estate", balance_eur: "448200", balance_dkk: null, weight_eur: "0.8" },
        { label: "checking", balance_eur: "112050", balance_dkk: null, weight_eur: "0.2" },
      ],
    },
  }),
}));
vi.mock("../src/components/EChart", () => ({
  EChart: ({ ariaLabel }: { readonly ariaLabel: string }) => (
    <div role="img" aria-label={ariaLabel} />
  ),
}));

const { AllocationDonut, AllocationSection } = await import("../src/pages/Overview");

const kinds = [
  ["real_estate", 448_200, 0.546],
  ["aktiedepot", 108_200, 0.132],
  ["ratepension", 80_000, 0.097],
  ["livrente", 78_700, 0.096],
  ["checking", 69_500, 0.085],
  ["aktiesparekonto", 24_900, 0.03],
  ["savings", 12_000, 0.015],
] as const;

describe("AllocationDonut", () => {
  it("gives seven asset kinds seven distinct swatches from the theme palette", () => {
    const slices = allocationSlices(
      kinds.map(([name, value, share]) => ({ name, value, share })),
      paletteTokens.dark.chart,
    );
    renderWithTheme(<AllocationDonut dimension="kind" slices={slices} />);

    const colors = screen
      .getAllByTestId("allocation-swatch")
      .map((swatch) => swatch.getAttribute("data-color"));
    expect(colors).toHaveLength(7);
    expect(new Set(colors).size).toBe(7);
    expect(colors).toEqual(paletteTokens.dark.chart.slice(0, 7));
  });

  it("uses the table as the legend and drops the chart legend", () => {
    const slices = allocationSlices(
      kinds.map(([name, value, share]) => ({ name, value, share })),
      paletteTokens.dark.chart,
    );
    renderWithTheme(<AllocationDonut dimension="kind" slices={slices} />);

    expect(
      screen.getByRole("img", { name: "Allocation by Asset kind (EUR leg)" }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(8);
    expect(screen.getByRole("cell", { name: "savings" })).toBeInTheDocument();
    expect(screen.getByText("EUR TOTAL")).toBeInTheDocument();
  });

  it("keeps light and dark palettes the same size with no repeated colours", () => {
    for (const mode of ["dark", "light"] as const) {
      const palette = paletteTokens[mode].chart;
      expect(palette).toHaveLength(8);
      expect(new Set(palette.map((color) => color.toLowerCase())).size).toBe(8);
    }
  });

  it("takes swatch colours from the active theme mode, not stale CSS variables", () => {
    const swatches = (mode: ThemeMode): (string | null)[] => {
      const { unmount } = renderWithTheme(
        <ThemeModeContext.Provider value={{ theme: mode, toggleTheme: () => {} }}>
          <AllocationSection />
        </ThemeModeContext.Provider>,
      );
      const colors = screen
        .getAllByTestId("allocation-swatch")
        .map((swatch) => swatch.getAttribute("data-color"));
      unmount();
      return colors;
    };
    expect(swatches("dark")).toEqual(paletteTokens.dark.chart.slice(0, 2));
    expect(swatches("light")).toEqual(paletteTokens.light.chart.slice(0, 2));
  });
});
