/** Light/dark theme state persisted to localStorage, applied via data-theme. */

import { useCallback, useEffect, useState } from "react";

export type Theme = "dark" | "light";

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

export function useTheme(): { theme: Theme; toggleTheme: () => void } {
  const [theme, setTheme] = useState<Theme>(readStoredTheme);

  useEffect(() => {
    document.documentElement.dataset["theme"] = theme;
    try {
      window.localStorage.setItem(storageKey, theme);
    } catch {
      // Persisting the preference is best-effort.
    }
  }, [theme]);

  const toggleTheme = useCallback(() => {
    setTheme((current) => (current === "dark" ? "light" : "dark"));
  }, []);

  return { theme, toggleTheme };
}

/** Chart palette resolved from the active CSS custom properties. */
export function chartPalette(): readonly string[] {
  const styles = getComputedStyle(document.documentElement);
  const palette = [1, 2, 3, 4, 5]
    .map((index) => styles.getPropertyValue(`--chart-${index}`).trim())
    .filter((color) => color.length > 0);
  return palette.length > 0 ? palette : ["#5b8def", "#43c59e", "#f2a65a", "#b083f0", "#e36588"];
}

export function chartTextColor(): string {
  const color = getComputedStyle(document.documentElement).getPropertyValue("--text-muted").trim();
  return color.length > 0 ? color : "#9aa3b2";
}
