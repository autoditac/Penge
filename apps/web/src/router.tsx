/** Route table: app shell layout with the four reporting surfaces. */

import { createBrowserRouter } from "react-router";

import { ImportsPage } from "./pages/Imports";
import { OverviewPage } from "./pages/Overview";
import { PerformancePage } from "./pages/Performance";
import { PlanningPage } from "./pages/Planning";
import { AppShell } from "./shell/AppShell";

export const router = createBrowserRouter([
  {
    path: "/",
    Component: AppShell,
    children: [
      { index: true, Component: OverviewPage },
      { path: "performance", Component: PerformancePage },
      { path: "imports", Component: ImportsPage },
      { path: "planning", Component: PlanningPage },
    ],
  },
]);
