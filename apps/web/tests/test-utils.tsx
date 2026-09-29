/** Test helper: renders React nodes wrapped in the Penge MUI theme so
 * components relying on theme tokens (colors, spacing) render correctly.
 */
import { ThemeProvider } from "@mui/material/styles";
import { render } from "@testing-library/react";
import type { RenderResult } from "@testing-library/react";
import type { ReactElement } from "react";

import { buildMuiTheme } from "../src/theme/muiTheme";

export function renderWithTheme(ui: ReactElement): RenderResult {
  return render(<ThemeProvider theme={buildMuiTheme("dark")}>{ui}</ThemeProvider>);
}
