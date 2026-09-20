/** Application shell: responsive navigation, theme toggle, freshness banner.
 *
 * Desktop (md+): a permanent side drawer.
 * Mobile: a compact top app bar plus a bottom navigation bar so every
 * surface stays one tap away with >=44px touch targets (#271).
 */

import { NavLink, Outlet, useLocation } from "react-router";
import AccountBalanceOutlinedIcon from "@mui/icons-material/AccountBalanceOutlined";
import AssignmentOutlinedIcon from "@mui/icons-material/AssignmentOutlined";
import Brightness4Icon from "@mui/icons-material/Brightness4";
import Brightness7Icon from "@mui/icons-material/Brightness7";
import DashboardOutlinedIcon from "@mui/icons-material/DashboardOutlined";
import TrendingUpOutlinedIcon from "@mui/icons-material/TrendingUpOutlined";
import UploadFileOutlinedIcon from "@mui/icons-material/UploadFileOutlined";
import AppBar from "@mui/material/AppBar";
import Box from "@mui/material/Box";
import BottomNavigation from "@mui/material/BottomNavigation";
import BottomNavigationAction from "@mui/material/BottomNavigationAction";
import Drawer from "@mui/material/Drawer";
import IconButton from "@mui/material/IconButton";
import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import Toolbar from "@mui/material/Toolbar";
import Tooltip from "@mui/material/Tooltip";
import useMediaQuery from "@mui/material/useMediaQuery";
import { useTheme as useMuiTheme } from "@mui/material/styles";

import { demoMode } from "../api/client";
import { useFreshness } from "../api/queries";
import { Pill } from "../components/primitives";
import { useTheme } from "../theme";

const navItems = [
  { to: "/", label: "Overview", end: true, icon: <DashboardOutlinedIcon /> },
  { to: "/performance", label: "Performance", end: false, icon: <TrendingUpOutlinedIcon /> },
  { to: "/imports", label: "Imports", end: false, icon: <UploadFileOutlinedIcon /> },
  { to: "/connections", label: "Connections", end: false, icon: <AccountBalanceOutlinedIcon /> },
  { to: "/planning", label: "Planning", end: false, icon: <AssignmentOutlinedIcon /> },
] as const;

const drawerWidth = 232;

export function AppShell(): React.JSX.Element {
  const { theme, toggleTheme } = useTheme();
  const muiTheme = useMuiTheme();
  const isDesktop = useMediaQuery(muiTheme.breakpoints.up("md"));

  return (
    <Box sx={{ display: "flex", minHeight: "100vh" }}>
      {isDesktop ? <DesktopNav theme={theme} onToggleTheme={toggleTheme} /> : null}
      <Box
        sx={{
          display: "flex",
          flexDirection: "column",
          minWidth: 0,
          flex: 1,
          pb: isDesktop ? 0 : "64px",
        }}
      >
        {isDesktop ? (
          <Toolbar
            component="header"
            sx={{
              justifyContent: "flex-end",
              gap: 1.5,
              borderBottom: "1px solid",
              borderColor: "divider",
            }}
          >
            <FreshnessBanner />
            {demoMode ? <Pill tone="watch">Demo data</Pill> : null}
          </Toolbar>
        ) : (
          <MobileTopBar theme={theme} onToggleTheme={toggleTheme} />
        )}
        <Box
          component="main"
          sx={{
            display: "flex",
            flexDirection: "column",
            gap: 2,
            p: { xs: 1.5, sm: 2, md: 3 },
            pb: { xs: 3, md: 6 },
            maxWidth: "1200px",
            width: "100%",
            mx: "auto",
          }}
        >
          <Outlet />
        </Box>
      </Box>
      {isDesktop ? null : <MobileBottomNav />}
    </Box>
  );
}

function DesktopNav({
  theme,
  onToggleTheme,
}: {
  readonly theme: "dark" | "light";
  readonly onToggleTheme: () => void;
}): React.JSX.Element {
  return (
    <Drawer
      variant="permanent"
      sx={{
        width: drawerWidth,
        flexShrink: 0,
        "& .MuiDrawer-paper": { width: drawerWidth, boxSizing: "border-box" },
      }}
    >
      <Stack sx={{ height: "100vh", p: 2, gap: 2.5 }}>
        <Brand />
        <Stack component="nav" aria-label="Primary" spacing={0.25}>
          {navItems.map((item) => (
            <NavItem key={item.to} item={item} />
          ))}
        </Stack>
        <Box sx={{ mt: "auto" }}>
          <ThemeToggleButton theme={theme} onToggle={onToggleTheme} fullWidth />
        </Box>
      </Stack>
    </Drawer>
  );
}

function Brand(): React.JSX.Element {
  return (
    <Stack direction="row" spacing={1.25} sx={{ alignItems: "center" }}>
      <Box
        aria-hidden="true"
        sx={{
          display: "grid",
          placeItems: "center",
          width: 36,
          height: 36,
          borderRadius: 2,
          background: (t) =>
            `linear-gradient(135deg, ${t.palette.primary.main}, ${t.palette.info.main})`,
          color: (t) => t.palette.primary.contrastText,
          fontSize: "1.2rem",
          fontWeight: 700,
        }}
      >
        ¤
      </Box>
      <Box>
        <Box component="strong" sx={{ display: "block", fontWeight: 700 }}>
          Penge
        </Box>
        <Box component="small" sx={{ color: "text.secondary", fontSize: "0.78rem" }}>
          Household finance
        </Box>
      </Box>
    </Stack>
  );
}

function NavItem({ item }: { readonly item: (typeof navItems)[number] }): React.JSX.Element {
  return (
    <NavLink to={item.to} end={item.end} style={{ textDecoration: "none" }}>
      {({ isActive }) => (
        <Stack
          direction="row"
          spacing={1.25}
          sx={{
            alignItems: "center",
            px: 1.25,
            py: 0.9,
            borderRadius: 2,
            minHeight: 44,
            color: isActive ? "text.primary" : "text.secondary",
            bgcolor: isActive
              ? (t) => `color-mix(in srgb, ${t.palette.primary.main} 16%, transparent)`
              : "transparent",
            fontWeight: isActive ? 700 : 500,
            "&:hover": { bgcolor: "background.default", color: "text.primary" },
          }}
        >
          {item.icon}
          <Box component="span" sx={{ fontSize: "0.92rem", fontWeight: "inherit" }}>
            {item.label}
          </Box>
        </Stack>
      )}
    </NavLink>
  );
}

function ThemeToggleButton({
  theme,
  onToggle,
  fullWidth = false,
}: {
  readonly theme: "dark" | "light";
  readonly onToggle: () => void;
  readonly fullWidth?: boolean;
}): React.JSX.Element {
  if (fullWidth) {
    return (
      <Stack
        component="button"
        type="button"
        onClick={onToggle}
        direction="row"
        spacing={1}
        sx={{
          alignItems: "center",
          justifyContent: "center",
          width: "100%",
          minHeight: 44,
          border: "1px solid",
          borderColor: "divider",
          borderRadius: 2,
          bgcolor: "background.default",
          color: "text.primary",
          font: "inherit",
          cursor: "pointer",
        }}
      >
        {theme === "dark" ? (
          <Brightness7Icon fontSize="small" />
        ) : (
          <Brightness4Icon fontSize="small" />
        )}
        <span>{theme === "dark" ? "Switch to light" : "Switch to dark"}</span>
      </Stack>
    );
  }
  return (
    <Tooltip title={theme === "dark" ? "Switch to light" : "Switch to dark"}>
      <IconButton
        onClick={onToggle}
        color="inherit"
        aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
        sx={{ minWidth: 44, minHeight: 44 }}
      >
        {theme === "dark" ? <Brightness7Icon /> : <Brightness4Icon />}
      </IconButton>
    </Tooltip>
  );
}

function MobileTopBar({
  theme,
  onToggleTheme,
}: {
  readonly theme: "dark" | "light";
  readonly onToggleTheme: () => void;
}): React.JSX.Element {
  return (
    <AppBar position="sticky" color="transparent">
      <Toolbar sx={{ gap: 1 }}>
        <Box
          aria-hidden="true"
          sx={{
            display: "grid",
            placeItems: "center",
            width: 30,
            height: 30,
            borderRadius: 1.5,
            background: (t) =>
              `linear-gradient(135deg, ${t.palette.primary.main}, ${t.palette.info.main})`,
            color: (t) => t.palette.primary.contrastText,
            fontWeight: 700,
          }}
        >
          ¤
        </Box>
        <Box component="strong" sx={{ fontWeight: 700, flexGrow: 1 }}>
          Penge
        </Box>
        <FreshnessBanner compact />
        {demoMode ? <Pill tone="watch">Demo</Pill> : null}
        <ThemeToggleButton theme={theme} onToggle={onToggleTheme} />
      </Toolbar>
    </AppBar>
  );
}

function MobileBottomNav(): React.JSX.Element {
  const location = useLocation();
  const activeIndex = navItems.findIndex((item) =>
    item.end ? location.pathname === item.to : location.pathname.startsWith(item.to),
  );

  return (
    <Paper
      sx={{ position: "fixed", bottom: 0, left: 0, right: 0, zIndex: (t) => t.zIndex.appBar }}
      elevation={0}
    >
      <BottomNavigation showLabels value={activeIndex === -1 ? 0 : activeIndex}>
        {navItems.map((item) => (
          <BottomNavigationAction
            key={item.to}
            component={NavLink}
            to={item.to}
            end={item.end}
            label={item.label}
            icon={item.icon}
            sx={{ minWidth: 0, minHeight: 56, py: 0.75 }}
          />
        ))}
      </BottomNavigation>
    </Paper>
  );
}

function FreshnessBanner({ compact = false }: { readonly compact?: boolean }): React.JSX.Element {
  const freshness = useFreshness();

  if (freshness.isPending) {
    return (
      <Box component="span" sx={{ color: "text.secondary", fontSize: "0.85rem" }}>
        {compact ? "Checking…" : "Checking mart freshness…"}
      </Box>
    );
  }
  if (freshness.isError) {
    return (
      <Box component="span" sx={{ color: "warning.main", fontSize: "0.85rem" }}>
        Read API unreachable
      </Box>
    );
  }

  const latestDates = freshness.data.marts
    .map((mart) => mart.latest_as_of)
    .filter((value): value is string => value !== null)
    .sort();
  const latest = latestDates[latestDates.length - 1];

  if (latest === undefined) {
    return (
      <Box component="span" sx={{ color: "warning.main", fontSize: "0.85rem" }}>
        Marts are empty
      </Box>
    );
  }
  return (
    <Box
      component="span"
      sx={{
        color: "text.secondary",
        fontSize: "0.85rem",
        whiteSpace: "nowrap",
        overflow: "hidden",
        textOverflow: "ellipsis",
      }}
    >
      {compact ? latest : `Data as of ${latest}`}
    </Box>
  );
}
