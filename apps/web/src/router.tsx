/** Route table for the reporting and evidence-first application surfaces. */

import { createBrowserRouter } from "react-router";

import { ConnectionsPage } from "./pages/Connections";
import { ImportsPage } from "./pages/Imports";
import { OverviewPage } from "./pages/Overview";
import { PerformancePage } from "./pages/Performance";
import { PlanningPage } from "./pages/Planning";
import { HouseholdPage } from "./pages/Household";
import { AskPengePage } from "./ask-penge/AskPengePage";
import { AskPengeE2EEntry } from "./ask-penge/AskPengeE2EEntry";
import { AppShell } from "./shell/AppShell";

function AskPengeRoute(): React.JSX.Element {
  return <AskPengeE2EEntry />;
}

export const router = createBrowserRouter([
  {
    path: "/",
    Component: AppShell,
    children: [
      { index: true, Component: OverviewPage },
      { path: "performance", Component: PerformancePage },
      { path: "imports", Component: ImportsPage },
      { path: "connections", Component: ConnectionsPage },
      { path: "planning", Component: PlanningPage },
      { path: "ask", Component: AskPengePage },
      { path: "ask/e2e", Component: AskPengeRoute },
      { path: "household/*", Component: HouseholdPage },
    ],
  },
]);
