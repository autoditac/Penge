import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "react-router";
import CssBaseline from "@mui/material/CssBaseline";
import { ThemeProvider } from "@mui/material/styles";

import { NotificationsProvider } from "./components/Notifications";
import { router } from "./router";
import { ThemeModeContext, useTheme } from "./theme";
import "./styles.css";

const root = document.getElementById("root");

if (root === null) {
  throw new Error("Penge WebUI root element was not found.");
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

function App(): React.JSX.Element {
  const { theme, toggleTheme, muiTheme } = useTheme();

  return (
    <ThemeModeContext.Provider value={{ theme, toggleTheme }}>
      <ThemeProvider theme={muiTheme}>
        <CssBaseline />
        <NotificationsProvider>
          <RouterProvider router={router} />
        </NotificationsProvider>
      </ThemeProvider>
    </ThemeModeContext.Provider>
  );
}

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
