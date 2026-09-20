/** Light/dark theme state persisted to localStorage; drives CSS vars + MUI. */

import { useCallback, useEffect, useMemo, useState } from "react";

import { applyThemeTokens, paletteTokens } from "./tokens";
import { buildMuiTheme } from "./muiTheme";
import type { ThemeMode } from "./tokens";

export type Theme = ThemeMode;

const storageKey = "penge-webui-theme";

function readStoredTheme(): Theme {
  try {
    const stored = window.localStorage.getItem(storageKey);
    if (stored === "light" || stored === "dark") {
      return stored;
    }
  } catch {
    // Storage unavailable (private mode); fall through to default.
  }
  return "dark";
}

export function useTheme(): {
  theme: Theme;
  toggleTheme: () => void;
  muiTheme: ReturnType<typeof buildMuiTheme>;
} {
  const [theme, setTheme] = useState<Theme>(readStoredTheme);

  useEffect(() => {
    document.documentElement.dataset["theme"] = theme;
    applyThemeTokens(theme);
    try {
      window.localStorage.setItem(storageKey, theme);
    } catch {
      // Persisting the preference is best-effort.
    }
  }, [theme]);

  const toggleTheme = useCallback(() => {
    setTheme((current) => (current === "dark" ? "light" : "dark"));
  }, []);

  const muiTheme = useMemo(() => buildMuiTheme(theme), [theme]);

  return { theme, toggleTheme, muiTheme };
}

/** Chart palette resolved from the active CSS custom properties. */
export function chartPalette(): readonly string[] {
  const styles = getComputedStyle(document.documentElement);
  const palette = [1, 2, 3, 4, 5]
    .map((index) => styles.getPropertyValue(`--chart-${index}`).trim())
    .filter((color) => color.length > 0);
  return palette.length > 0 ? palette : paletteTokens.dark.chart;
}

export function chartTextColor(): string {
  const color = getComputedStyle(document.documentElement).getPropertyValue("--text-muted").trim();
  return color.length > 0 ? color : paletteTokens.dark.textMuted;
}
