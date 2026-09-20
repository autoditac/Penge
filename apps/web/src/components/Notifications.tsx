/** App-wide toast notifications (Snackbar + Alert), for background actions
 * like import commits or connection syncs where a page transition would
 * otherwise hide the result (#271 acceptance: reusable notifications).
 */

import { createContext, useCallback, useContext, useMemo, useState } from "react";
import Alert from "@mui/material/Alert";
import Snackbar from "@mui/material/Snackbar";

export type NotificationSeverity = "success" | "error" | "info" | "warning";

type Notification = {
  readonly id: number;
  readonly message: string;
  readonly severity: NotificationSeverity;
};

type NotifyFn = (message: string, severity?: NotificationSeverity) => void;

const NotificationsContext = createContext<NotifyFn | null>(null);

let nextId = 0;

export function NotificationsProvider({
  children,
}: {
  readonly children: React.ReactNode;
}): React.JSX.Element {
  const [queue, setQueue] = useState<readonly Notification[]>([]);

  const notify = useCallback<NotifyFn>((message, severity = "info") => {
    nextId += 1;
    const notification: Notification = { id: nextId, message, severity };
    setQueue((current) => [...current, notification]);
  }, []);

  const current = queue[0];

  const handleClose = useCallback(() => {
    setQueue((existing) => existing.slice(1));
  }, []);

  const value = useMemo(() => notify, [notify]);

  return (
    <NotificationsContext.Provider value={value}>
      {children}
      <Snackbar
        open={current !== undefined}
        autoHideDuration={5000}
        onClose={handleClose}
        anchorOrigin={{ vertical: "bottom", horizontal: "center" }}
      >
        {current !== undefined ? (
          <Alert
            onClose={handleClose}
            severity={current.severity}
            variant="filled"
            sx={{ borderRadius: 2.5 }}
          >
            {current.message}
          </Alert>
        ) : undefined}
      </Snackbar>
    </NotificationsContext.Provider>
  );
}

/** Fire a toast notification. Throws outside {@link NotificationsProvider}. */
export function useNotify(): NotifyFn {
  const notify = useContext(NotificationsContext);
  if (notify === null) {
    throw new Error("useNotify must be used within a NotificationsProvider");
  }
  return notify;
}
