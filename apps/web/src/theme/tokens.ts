/** Nordnet-inspired design tokens — the single source of truth for color.
 *
 * These values back both the CSS custom properties (consumed by legacy
 * className-based styles and the ECharts palette helpers) and the MUI theme
 * palette, so every surface — MUI components and plain CSS alike — draws
 * from the same numbers. Do not hardcode hex values elsewhere; extend this
 * file instead.
 */

export type ThemeMode = "dark" | "light";

export type ColorTokens = {
  readonly background: string;
  readonly backgroundRaised: string;
  readonly backgroundInset: string;
  readonly border: string;
  readonly text: string;
  readonly textMuted: string;
  readonly accent: string;
  readonly accentContrast: string;
  readonly good: string;
  readonly watch: string;
  readonly critical: string;
  readonly chart: readonly [string, string, string, string, string];
};

/**
 * Dark is the primary, default surface: deep charcoal/slate panels with a
 * single restrained turquoise accent, mirroring a calm Nordic trading
 * cockpit rather than a generic Material palette.
 */
const dark: ColorTokens = {
  background: "#0b0f14",
  backgroundRaised: "#12181f",
  backgroundInset: "#0e1319",
  border: "rgba(148, 163, 184, 0.14)",
  text: "#e8ecf1",
  textMuted: "#8b96a5",
  accent: "#2dd4bf",
  accentContrast: "#04211d",
  good: "#34d399",
  watch: "#f2b155",
  critical: "#f36a80",
  chart: ["#2dd4bf", "#5b8def", "#f2b155", "#b083f0", "#f36a80"],
};

const light: ColorTokens = {
  background: "#f2f4f8",
  backgroundRaised: "#ffffff",
  backgroundInset: "#e9edf3",
  border: "rgba(51, 65, 85, 0.16)",
  text: "#111827",
  textMuted: "#5b6678",
  accent: "#0f9c8d",
  accentContrast: "#ffffff",
  good: "#0f8f63",
  watch: "#b06a10",
  critical: "#c23b5e",
  chart: ["#0f9c8d", "#2f6bdb", "#b06a10", "#7c4fd0", "#c23b5e"],
};

export const paletteTokens: Record<ThemeMode, ColorTokens> = { dark, light };

const cssVarNames = {
  background: "--bg",
  backgroundRaised: "--bg-raised",
  backgroundInset: "--bg-inset",
  border: "--border",
  text: "--text",
  textMuted: "--text-muted",
  accent: "--accent",
  accentContrast: "--accent-contrast",
  good: "--good",
  watch: "--watch",
  critical: "--critical",
} as const satisfies Record<keyof Omit<ColorTokens, "chart">, string>;

/** Applies a mode's tokens as CSS custom properties on the document root. */
export function applyThemeTokens(mode: ThemeMode): void {
  const tokens = paletteTokens[mode];
  const root = document.documentElement.style;
  for (const [key, cssVar] of Object.entries(cssVarNames)) {
    root.setProperty(cssVar, tokens[key as keyof typeof cssVarNames]);
  }
  tokens.chart.forEach((color, index) => {
    root.setProperty(`--chart-${index + 1}`, color);
  });
}
