/** Shared presentational building blocks: EUR/DKK pairs, states, KPI cards,
 * panels, status chips, and segmented controls. Every page composes these
 * instead of hand-rolled markup so the Nordnet-inspired look stays
 * consistent (issue #271).
 */

import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import CircularProgress from "@mui/material/CircularProgress";
import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Typography from "@mui/material/Typography";

import { formatMoney } from "../money";
import type { Currency } from "../money";

export type Tone = "good" | "watch" | "critical" | "info" | "neutral";

type ToneKey = "success" | "warning" | "error" | "info";

type TonePalette = { readonly text: string; readonly key: ToneKey | undefined };

const tonePalette: Record<Tone, TonePalette> = {
  good: { text: "success.main", key: "success" },
  watch: { text: "warning.main", key: "warning" },
  critical: { text: "error.main", key: "error" },
  info: { text: "info.main", key: "info" },
  neutral: { text: "text.secondary", key: undefined },
};

type MoneyPairProps = {
  readonly eur: number | null;
  readonly dkk: number | null;
  readonly primary?: Currency;
};

/** EUR and DKK shown in parallel — never one silently picked as base (ADR-0004). */
export function MoneyPair({ eur, dkk, primary = "DKK" }: MoneyPairProps): React.JSX.Element {
  const [first, second]: readonly [
    readonly [number | null, Currency],
    readonly [number | null, Currency],
  ] =
    primary === "DKK"
      ? ([
          [dkk, "DKK"],
          [eur, "EUR"],
        ] as const)
      : ([
          [eur, "EUR"],
          [dkk, "DKK"],
        ] as const);

  return (
    <Stack className="moneyPair" spacing={0} sx={{ fontVariantNumeric: "tabular-nums" }}>
      <Box component="strong" sx={{ fontWeight: 700, fontSize: "1rem" }}>
        {formatMoney(first[0], first[1])}
      </Box>
      <Box component="small" sx={{ color: "text.secondary", fontSize: "0.82rem" }}>
        {formatMoney(second[0], second[1])}
      </Box>
    </Stack>
  );
}

type MetricCardProps = {
  readonly label: string;
  readonly children: React.ReactNode;
  readonly detail?: string;
  readonly tone?: Tone;
};

/** Compact KPI tile used in dashboard header strips. */
export function MetricCard({
  label,
  children,
  detail,
  tone = "info",
}: MetricCardProps): React.JSX.Element {
  return (
    <Paper
      component="article"
      variant="outlined"
      sx={{
        px: 1.75,
        py: 1.1,
        minWidth: "9rem",
        bgcolor: "background.default",
        borderRadius: 2.5,
      }}
    >
      <Box
        component="span"
        sx={{
          display: "block",
          fontSize: "0.72rem",
          fontWeight: 600,
          letterSpacing: "0.06em",
          textTransform: "uppercase",
          color: "text.secondary",
        }}
      >
        {label}
      </Box>
      <Box
        sx={{
          fontSize: "1.05rem",
          fontWeight: 700,
          color: tonePalette[tone].text,
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {children}
      </Box>
      {detail !== undefined ? (
        <Box component="small" sx={{ color: "text.secondary", fontSize: "0.78rem" }}>
          {detail}
        </Box>
      ) : null}
    </Paper>
  );
}

/** @deprecated Use {@link MetricCard}. Kept temporarily during the #271 rollout. */
export const KpiCard = MetricCard;

export function LoadingState({ label }: { readonly label: string }): React.JSX.Element {
  return (
    <Stack
      role="status"
      aria-live="polite"
      direction="row"
      spacing={1.25}
      sx={{
        alignItems: "center",
        border: "1px dashed",
        borderColor: "divider",
        borderRadius: 3,
        bgcolor: "background.paper",
        color: "text.secondary",
        p: 3,
      }}
    >
      <CircularProgress
        size={18}
        thickness={5}
        aria-hidden="true"
        sx={{
          // Respect prefers-reduced-motion (#271 acceptance: preserve
          // reduced-motion support) by freezing the spin animation; the
          // spinner still communicates a pending state visually via its
          // partial ring, just without continuous motion.
          "@media (prefers-reduced-motion: reduce)": {
            animation: "none",
            "& .MuiCircularProgress-circle": { animation: "none" },
          },
        }}
      />
      <Box component="p" sx={{ m: 0 }}>
        Loading {label}…
      </Box>
    </Stack>
  );
}

type ErrorStateProps = {
  readonly label: string;
  readonly error: Error;
  readonly onRetry?: () => void;
};

export function ErrorState({ label, error, onRetry }: ErrorStateProps): React.JSX.Element {
  return (
    <Alert
      severity="error"
      variant="outlined"
      action={
        onRetry !== undefined ? (
          <Button color="inherit" size="small" onClick={onRetry} sx={{ minHeight: "2.75rem" }}>
            Retry
          </Button>
        ) : undefined
      }
      sx={{ borderRadius: 3 }}
    >
      <Box component="strong" sx={{ display: "block" }}>
        Could not load {label}.
      </Box>
      <Box component="p" sx={{ fontSize: "0.85rem", m: 0 }}>
        {error.message}
      </Box>
      <Box component="p" sx={{ fontSize: "0.85rem", m: 0 }}>
        Start the read API with <code>just api-dev</code>, or set <code>VITE_PENGE_DEMO=true</code>{" "}
        for synthetic demo data.
      </Box>
    </Alert>
  );
}

export function EmptyState({ label }: { readonly label: string }): React.JSX.Element {
  return (
    <Box
      role="note"
      sx={{
        border: "1px dashed",
        borderColor: "divider",
        borderRadius: 3,
        bgcolor: "background.paper",
        color: "text.secondary",
        p: 3,
      }}
    >
      <Box component="p" sx={{ m: 0 }}>
        No {label} available yet. Run an ingest + dbt build to populate the marts.
      </Box>
    </Box>
  );
}

type PageHeaderProps = {
  readonly title: string;
  readonly description?: React.ReactNode;
  readonly badge?: React.ReactNode;
};

/** Page-level heading used at the top of every route (#271). */
export function PageHeader({ title, description, badge }: PageHeaderProps): React.JSX.Element {
  return (
    <Box component="section" sx={{ mb: 0.5 }}>
      <Typography component="h1" variant="h4" sx={{ fontWeight: 700, mb: 0.5 }}>
        {title}
      </Typography>
      {description !== undefined ? (
        <Typography color="text.secondary" sx={{ maxWidth: "62ch" }}>
          {description}
        </Typography>
      ) : null}
      {badge !== undefined ? <Box sx={{ mt: 1 }}>{badge}</Box> : null}
    </Box>
  );
}

type PanelProps = {
  readonly eyebrow?: string;
  readonly title: React.ReactNode;
  readonly actions?: React.ReactNode;
  readonly children: React.ReactNode;
};

/** A raised, bordered content panel with a consistent title/actions header. */
export function Panel({ eyebrow, title, actions, children }: PanelProps): React.JSX.Element {
  return (
    <Paper
      component="section"
      variant="outlined"
      sx={{
        p: { xs: 1.75, sm: 2.25 },
        borderRadius: 3.5,
        bgcolor: "background.paper",
        // Prevent intrinsic content (e.g. a segmented control row) from
        // pushing this panel wider than its grid/flex track, which would
        // otherwise cause horizontal page overflow on narrow viewports.
        minWidth: 0,
      }}
    >
      <Stack
        direction="row"
        sx={{
          flexWrap: "wrap",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: 1.5,
          mb: 1.5,
        }}
      >
        <Box>
          {eyebrow !== undefined ? (
            <Box
              component="p"
              sx={{
                m: 0,
                mb: 0.25,
                fontSize: "0.72rem",
                fontWeight: 600,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                color: "text.secondary",
              }}
            >
              {eyebrow}
            </Box>
          ) : null}
          <Typography component="h2" sx={{ m: 0, fontSize: "1.15rem", fontWeight: 700 }}>
            {title}
          </Typography>
        </Box>
        {actions !== undefined ? <Box>{actions}</Box> : null}
      </Stack>
      {children}
    </Paper>
  );
}

type PillProps = {
  readonly tone?: Tone;
  readonly children: React.ReactNode;
};

/** Small status/count chip (replaces `.pill`/`.badge`/`.statusPill`). */
export function Pill({ tone = "neutral", children }: PillProps): React.JSX.Element {
  const { key } = tonePalette[tone];
  return (
    <Chip
      size="small"
      variant={key === undefined ? "outlined" : "filled"}
      label={children}
      sx={
        key === undefined
          ? undefined
          : {
              bgcolor: (theme) => `color-mix(in srgb, ${theme.palette[key].main} 16%, transparent)`,
              color: (theme) => theme.palette[key].main,
              border: "none",
              fontWeight: 700,
            }
      }
    />
  );
}

export type SegmentedOption<T extends string> = {
  readonly value: T;
  readonly label: string;
};

type SegmentedControlProps<T extends string> = {
  readonly options: readonly SegmentedOption<T>[];
  readonly value: T;
  readonly onChange: (value: T) => void;
  readonly ariaLabel: string;
};

/** Compact single-select control for chart ranges, dimensions, and filters. */
export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
}: SegmentedControlProps<T>): React.JSX.Element {
  return (
    // Scrolls horizontally within its own bounds on narrow viewports instead
    // of forcing the surrounding panel wider than the page (#271): a row of
    // several options (e.g. "Asset kind" / "Currency" / "Household member")
    // does not fit 390px width without wrapping labels mid-word.
    <Box sx={{ overflowX: "auto", WebkitOverflowScrolling: "touch", minWidth: 0 }}>
      <ToggleButtonGroup
        value={value}
        exclusive
        size="small"
        aria-label={ariaLabel}
        onChange={(_event, next: T | null) => {
          if (next !== null) {
            onChange(next);
          }
        }}
        sx={{
          bgcolor: "background.default",
          "& .MuiToggleButton-root": {
            // 2.75rem (44px) keeps this an accessible mobile touch target
            // (#271 acceptance: minimum 44px mobile targets).
            minHeight: "2.75rem",
            minWidth: "2.75rem",
            px: 1.4,
            textTransform: "none",
            fontWeight: 600,
            color: "text.secondary",
            border: "1px solid",
            borderColor: "divider",
            whiteSpace: "nowrap",
          },
          "& .Mui-selected": {
            color: "text.primary",
            bgcolor: (theme) =>
              `color-mix(in srgb, ${theme.palette.primary.main} 20%, transparent)`,
          },
        }}
      >
        {options.map((option) => (
          <ToggleButton
            key={option.value}
            value={option.value}
            aria-pressed={value === option.value}
          >
            {option.label}
          </ToggleButton>
        ))}
      </ToggleButtonGroup>
    </Box>
  );
}

/** Wraps dense tables so they scroll horizontally within their own bounds
 * instead of overflowing the page or squeezing columns illegibly (#271). */
export function TableScroll({
  children,
}: {
  readonly children: React.ReactNode;
}): React.JSX.Element {
  return (
    <Box sx={{ overflowX: "auto", mt: 1.25, WebkitOverflowScrolling: "touch" }}>{children}</Box>
  );
}
