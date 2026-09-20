/** Custom Penge MUI theme — Nordnet-inspired, not generic Material Design.
 *
 * Flat surfaces (no drop shadows), restrained turquoise accent, tabular
 * numerals for financial figures, and reduced-motion-aware transitions.
 * See ADR-0045 for the toolkit decision and rationale.
 */

import { createTheme } from "@mui/material/styles";
import type { Theme } from "@mui/material/styles";

import type { ThemeMode } from "./tokens";
import { paletteTokens } from "./tokens";

const prefersReducedMotion =
  typeof window !== "undefined" && "matchMedia" in window
    ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
    : false;

export function buildMuiTheme(mode: ThemeMode): Theme {
  const tokens = paletteTokens[mode];

  return createTheme({
    palette: {
      mode,
      background: {
        default: tokens.background,
        paper: tokens.backgroundRaised,
      },
      text: {
        primary: tokens.text,
        secondary: tokens.textMuted,
      },
      divider: tokens.border,
      primary: {
        main: tokens.accent,
        contrastText: tokens.accentContrast,
      },
      success: { main: tokens.good },
      warning: { main: tokens.watch },
      error: { main: tokens.critical },
      info: { main: tokens.accent },
    },
    shape: { borderRadius: 10 },
    typography: {
      fontFamily: '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
      button: { textTransform: "none", fontWeight: 600 },
    },
    transitions: prefersReducedMotion
      ? {
          create: () => "none",
        }
      : undefined,
    components: {
      MuiPaper: {
        styleOverrides: {
          root: {
            backgroundImage: "none",
            border: `1px solid ${tokens.border}`,
          },
        },
        defaultProps: { elevation: 0 },
      },
      MuiAppBar: {
        styleOverrides: {
          root: {
            backgroundImage: "none",
            backgroundColor: tokens.backgroundRaised,
            borderBottom: `1px solid ${tokens.border}`,
          },
        },
        defaultProps: { elevation: 0 },
      },
      MuiDrawer: {
        styleOverrides: {
          paper: {
            backgroundImage: "none",
            backgroundColor: tokens.backgroundRaised,
            borderRight: `1px solid ${tokens.border}`,
          },
        },
      },
      MuiButtonBase: {
        defaultProps: { disableRipple: prefersReducedMotion },
      },
      MuiButton: {
        styleOverrides: {
          root: { borderRadius: 9 },
        },
      },
      MuiChip: {
        styleOverrides: {
          root: { fontWeight: 600 },
        },
      },
      MuiTableCell: {
        styleOverrides: {
          root: { borderColor: tokens.border },
        },
      },
      MuiBottomNavigation: {
        styleOverrides: {
          root: {
            backgroundColor: tokens.backgroundRaised,
            borderTop: `1px solid ${tokens.border}`,
          },
        },
      },
    },
  });
}
