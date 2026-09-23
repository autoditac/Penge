/** Button to trigger the guarded dbt-only refresh from the WebUI (#285).
 *
 * Does not re-sync bank connections — it only reruns the shadow
 * build/test/promote pipeline described in ADR-0046, reusing the same
 * shared lock and durable pending marker as the manual connection sync and
 * the scheduled worker. Shows an indeterminate progress bar (the exact
 * dbt-build duration can't be estimated up front, so a fake percentage
 * would be misleading) and disables itself while a refresh is in flight to
 * prevent duplicate submissions.
 */

import { useEffect } from "react";
import Button from "@mui/material/Button";
import LinearProgress from "@mui/material/LinearProgress";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { useTriggerMetaRefresh } from "../api/queries";
import { useNotify } from "./Notifications";

export function MetaRefreshButton({
  compact = false,
}: {
  readonly compact?: boolean;
}): React.JSX.Element {
  const refresh = useTriggerMetaRefresh();
  const notify = useNotify();

  useEffect(() => {
    if (refresh.isSuccess) {
      notify(`Analytics refreshed (as of ${refresh.data.completed_at}).`, "success");
    }
  }, [refresh.isSuccess, refresh.data, notify]);

  useEffect(() => {
    if (refresh.isError) {
      notify(refresh.error.message, "error");
    }
  }, [refresh.isError, refresh.error, notify]);

  return (
    <Stack spacing={0.5} sx={{ minWidth: compact ? undefined : 176 }}>
      <Button
        type="button"
        variant="outlined"
        size="small"
        disabled={refresh.isPending}
        onClick={() => refresh.mutate()}
        sx={{ minHeight: "2.75rem", whiteSpace: "nowrap" }}
      >
        {refresh.isPending ? "Refreshing…" : compact ? "Refresh" : "Refresh analytics"}
      </Button>
      {refresh.isPending ? (
        <Stack spacing={0.25} aria-live="polite">
          <LinearProgress aria-label="Refreshing analytics" />
          <Typography component="span" color="text.secondary" sx={{ fontSize: "0.72rem" }}>
            Building and validating marts…
          </Typography>
        </Stack>
      ) : null}
    </Stack>
  );
}
