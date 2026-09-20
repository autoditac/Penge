/** Light/dark theme state persisted to localStorage; drives CSS vars + MUI. */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

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

/** Owns the single source of truth for the active theme (call once, at the
 * app root). Every other component reads it via {@link useThemeMode} so the
 * MUI theme, CSS custom properties, and chart palette never fall out of
 * sync with each other. */
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
    setTheme((current) => {
      const next: Theme = current === "dark" ? "light" : "dark";
      // Apply CSS custom properties synchronously (before React renders any
      // consumer for this update), not only in the effect above: an effect
      // runs after the commit that reads them (e.g. chart palette lookups
      // during render), which otherwise leaves charts one toggle behind.
      document.documentElement.dataset["theme"] = next;
      applyThemeTokens(next);
      return next;
    });
  }, []);

  const muiTheme = useMemo(() => buildMuiTheme(theme), [theme]);

  return { theme, toggleTheme, muiTheme };
}

type ThemeModeValue = { readonly theme: Theme; readonly toggleTheme: () => void };

/** Provided once by the app root ({@link useTheme}'s owner); consumed by
 * {@link useThemeMode} so nested components (shell, pages) share the same
 * theme state instead of instantiating their own independent copy. */
export const ThemeModeContext = createContext<ThemeModeValue | null>(null);

/** Reads the shared theme mode + toggle set up by the app root. Falls back
 * to a static dark default (no-op toggle) when rendered without a provider,
 * e.g. in component tests that do not exercise theme switching. */
export function useThemeMode(): ThemeModeValue {
  const context = useContext(ThemeModeContext);
  return context ?? { theme: "dark", toggleTheme: () => {} };
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
