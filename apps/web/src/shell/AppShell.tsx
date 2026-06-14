/** Application shell: sidebar navigation, theme toggle, freshness banner. */

import { NavLink, Outlet } from "react-router";

import { demoMode } from "../api/client";
import { useFreshness } from "../api/queries";
import { useTheme } from "../theme";

const navItems = [
  { to: "/", label: "Overview", end: true },
  { to: "/performance", label: "Performance", end: false },
  { to: "/imports", label: "Imports", end: false },
  { to: "/connections", label: "Connections", end: false },
  { to: "/planning", label: "Planning", end: false },
] as const;

export function AppShell(): React.JSX.Element {
  const { theme, toggleTheme } = useTheme();

  return (
    <div className="appShell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brandMark" aria-hidden="true">
            ¤
          </span>
          <div>
            <strong>Penge</strong>
            <small>Household finance</small>
          </div>
        </div>
        <nav aria-label="Primary">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => (isActive ? "navLink navLinkActive" : "navLink")}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebarFooter">
          <button type="button" className="themeToggle" onClick={toggleTheme}>
            {theme === "dark" ? "Switch to light" : "Switch to dark"}
          </button>
        </div>
      </aside>
      <div className="contentColumn">
        <header className="topBar">
          <FreshnessBanner />
          {demoMode ? <span className="demoBadge">Demo data</span> : null}
        </header>
        <main className="pageContainer">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

function FreshnessBanner(): React.JSX.Element {
  const freshness = useFreshness();

  if (freshness.isPending) {
    return <span className="freshness">Checking mart freshness…</span>;
  }
  if (freshness.isError) {
    return <span className="freshness freshnessStale">Read API unreachable</span>;
  }

  const latestDates = freshness.data.marts
    .map((mart) => mart.latest_as_of)
    .filter((value): value is string => value !== null)
    .sort();
  const latest = latestDates[latestDates.length - 1];

  if (latest === undefined) {
    return <span className="freshness freshnessStale">Marts are empty</span>;
  }
  return <span className="freshness">Data as of {latest}</span>;
}
