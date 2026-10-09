import { useEffect, useMemo, useRef, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import Drawer from "@mui/material/Drawer";
import IconButton from "@mui/material/IconButton";
import Link from "@mui/material/Link";
import List from "@mui/material/List";
import ListItem from "@mui/material/ListItem";
import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import useMediaQuery from "@mui/material/useMediaQuery";
import { useTheme } from "@mui/material/styles";

import { PageHeader, Panel, Pill } from "../components/primitives";
import type { Tone } from "../components/primitives";
import type {
  AskStreamCompletionEvent,
  AskStreamErrorEvent,
  AskStreamEvent,
  AskStreamEvidenceEvent,
  AskStreamToolEvent,
  AskTransport,
  AskTransportSession,
} from "./contract";
import { createAskStreamValidator } from "./contract";

type FilterValue = "all" | "fresh" | "attention";
type AuthState = "linked" | "not-linked" | "expired" | "not-configured";
type StreamState = "idle" | "streaming" | "complete" | "cancelled" | "error" | "disconnected";
type ServiceState = "not-configured" | "loading" | "ready" | "error";

type AskPengePageProps = {
  readonly transport?: AskTransport;
  readonly authState?: AuthState;
  readonly githubLogin?: string | null;
  readonly modelAvailable?: boolean;
  readonly featureEnabled?: boolean;
  readonly serviceState?: ServiceState;
  readonly serviceError?: string | null;
  readonly onLinkGitHub?: () => void;
  readonly onUnlinkGitHub?: () => void;
  readonly onRetryStatus?: () => void;
};

const FILTER_TABS: ReadonlyArray<{ value: FilterValue; label: string }> = [
  { value: "all", label: "All" },
  { value: "fresh", label: "Fresh" },
  { value: "attention", label: "Needs attention" },
] as const;

const ANSWER_BUFFER_MS = 120;

const toolTone: Record<AskStreamToolEvent["status"], Tone> = {
  started: "info",
  running: "watch",
  complete: "good",
  failed: "critical",
};

const evidenceTone: Record<AskStreamEvidenceEvent["coverage"], Tone> = {
  full: "good",
  partial: "watch",
  missing: "critical",
};

const freshnessTone: Record<AskStreamEvidenceEvent["freshness"], Tone> = {
  fresh: "good",
  stale: "watch",
  missing: "critical",
};

function streamErrorTitle(error: AskStreamErrorEvent): string {
  switch (error.code) {
    case "auth_expired":
      return "GitHub session expired";
    case "hydrafusion_unavailable":
      return "Exact HydraFusion data is unavailable";
    case "rate_limit":
      return "Copilot rate limit reached";
    case "session_interrupted":
      return "Connection interrupted";
    case "data_missing":
      return "Required source data is missing";
    case "missing_fx":
      return "EUR/DKK FX evidence is missing";
    case "tool_timeout":
      return "Evidence lookup timed out";
  }
}

export function AskPengePage({
  transport,
  authState = "not-configured",
  githubLogin = null,
  modelAvailable = false,
  featureEnabled = transport !== undefined,
  serviceState = transport === undefined ? "not-configured" : "ready",
  serviceError = null,
  onLinkGitHub,
  onUnlinkGitHub,
  onRetryStatus,
}: AskPengePageProps): React.JSX.Element {
  return (
    <AskPengeWorkbench
      transport={transport}
      authState={authState}
      githubLogin={githubLogin}
      modelAvailable={modelAvailable}
      featureEnabled={featureEnabled}
      serviceState={serviceState}
      serviceError={serviceError}
      onLinkGitHub={onLinkGitHub}
      onUnlinkGitHub={onUnlinkGitHub}
      onRetryStatus={onRetryStatus}
    />
  );
}

type AskPengeWorkbenchProps = {
  readonly transport: AskTransport | undefined;
  readonly authState: AuthState;
  readonly githubLogin: string | null;
  readonly modelAvailable: boolean;
  readonly featureEnabled: boolean;
  readonly serviceState: ServiceState;
  readonly serviceError: string | null;
  readonly onLinkGitHub: (() => void) | undefined;
  readonly onUnlinkGitHub: (() => void) | undefined;
  readonly onRetryStatus: (() => void) | undefined;
};

function AskPengeWorkbench({
  transport,
  authState,
  githubLogin,
  modelAvailable,
  featureEnabled,
  serviceState,
  serviceError,
  onLinkGitHub,
  onUnlinkGitHub,
  onRetryStatus,
}: AskPengeWorkbenchProps): React.JSX.Element {
  const [events, setEvents] = useState<readonly AskStreamEvent[]>([]);
  const [answer, setAnswer] = useState<string>("");
  const [draft, setDraft] = useState<string>(
    "Which balances and tax-check items need a fresh review before the next quarter?",
  );
  const [streamState, setStreamState] = useState<StreamState>("idle");
  const [activeFilter, setActiveFilter] = useState<FilterValue>("all");
  const [drawerOpen, setDrawerOpen] = useState<boolean>(false);
  const [railCollapsed, setRailCollapsed] = useState<boolean>(false);
  const [streamError, setStreamError] = useState<AskStreamErrorEvent | null>(null);
  const [contractError, setContractError] = useState<string | null>(null);
  const sessionRef = useRef<AskTransportSession | null>(null);
  const unsubscribeRef = useRef<(() => void) | null>(null);
  const answerRef = useRef<string>("");
  const answerBufferRef = useRef<string>("");
  const answerTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("md"));
  const canAsk =
    transport !== undefined &&
    serviceState === "ready" &&
    featureEnabled &&
    authState === "linked" &&
    modelAvailable;

  useEffect(() => {
    return () => {
      sessionRef.current?.close();
      unsubscribeRef.current?.();
      flushBufferedAnswer(false);
    };
  }, []);

  function flushBufferedAnswer(publish = true): void {
    if (answerTimerRef.current !== null) {
      clearTimeout(answerTimerRef.current);
      answerTimerRef.current = null;
    }
    if (answerBufferRef.current.length === 0) {
      return;
    }

    answerRef.current += answerBufferRef.current;
    answerBufferRef.current = "";
    if (publish) {
      setAnswer(answerRef.current);
    }
  }

  function bufferAnswerDelta(delta: string): void {
    answerBufferRef.current += delta;
    if (answerTimerRef.current === null) {
      answerTimerRef.current = setTimeout(flushBufferedAnswer, ANSWER_BUFFER_MS);
    }
  }

  async function stopSession(): Promise<void> {
    const session = sessionRef.current;
    const unsubscribe = unsubscribeRef.current;
    if (sessionRef.current === session) {
      sessionRef.current = null;
    }
    if (unsubscribeRef.current === unsubscribe) {
      unsubscribeRef.current = null;
    }
    unsubscribe?.();
    flushBufferedAnswer();
    setStreamState("cancelled");
    try {
      await session?.stop();
    } catch {
      setContractError(
        "The server could not confirm cancellation. The local stream was closed; reconnect before asking again.",
      );
      setStreamState("disconnected");
    } finally {
      session?.close();
    }
  }

  function startSession(question: string): void {
    if (!question.trim() || !canAsk || transport === undefined) {
      return;
    }

    if (sessionRef.current !== null) {
      sessionRef.current.close();
    }
    if (unsubscribeRef.current !== null) {
      unsubscribeRef.current();
    }

    const nextSession = transport.start({ question: question.trim() });
    const validateEvent = createAskStreamValidator();
    sessionRef.current = nextSession;
    flushBufferedAnswer(false);
    answerRef.current = "";
    answerBufferRef.current = "";
    setAnswer("");
    setEvents([]);
    setStreamState("streaming");
    setStreamError(null);
    setContractError(null);

    let unsubscribe = (): void => undefined;
    const unsubscribeAfterDispatch = (): void => {
      queueMicrotask(() => {
        unsubscribe();
        if (unsubscribeRef.current === unsubscribe) {
          unsubscribeRef.current = null;
        }
      });
    };
    const finishLocalSession = (): void => {
      nextSession.close();
      if (sessionRef.current === nextSession) {
        sessionRef.current = null;
      }
      unsubscribeAfterDispatch();
    };
    unsubscribe = nextSession.subscribe((candidate) => {
      let event: AskStreamEvent;
      try {
        event = validateEvent(candidate);
      } catch {
        finishLocalSession();
        setContractError(
          "The answer stream did not match Ask Penge protocol 1.0. Reconnect after the backend contract is updated.",
        );
        setStreamState("error");
        return;
      }

      if (event.type === "text") {
        bufferAnswerDelta(event.delta);
        return;
      }

      setEvents((previous) => [...previous, event]);
      if (event.type === "error") {
        flushBufferedAnswer();
        setStreamError(event);
        setStreamState(event.code === "session_interrupted" ? "disconnected" : "error");
        finishLocalSession();
      }
      if (event.type === "completion") {
        flushBufferedAnswer();
        setStreamState(event.finishReason === "cancelled" ? "cancelled" : "complete");
        finishLocalSession();
      }
    });
    unsubscribeRef.current = unsubscribe;
  }

  const isStreaming = streamState === "streaming";

  const evidenceItems = useMemo(
    () => events.filter((event): event is AskStreamEvidenceEvent => event.type === "evidence"),
    [events],
  );

  const toolEvents = useMemo(
    () => events.filter((event): event is AskStreamToolEvent => event.type === "tool"),
    [events],
  );

  const completion = useMemo(
    () =>
      events
        .filter((event): event is AskStreamCompletionEvent => event.type === "completion")
        .at(-1),
    [events],
  );

  const visibleEvidence = useMemo(() => {
    if (activeFilter === "all") {
      return evidenceItems;
    }

    if (activeFilter === "fresh") {
      return evidenceItems.filter((item) => item.freshness === "fresh");
    }

    return evidenceItems.filter((item) => item.coverage !== "full" || item.freshness !== "fresh");
  }, [activeFilter, evidenceItems]);

  const selectedEvidence = visibleEvidence;

  const submitQuestion = (event: React.FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    if (!draft.trim()) {
      return;
    }
    startSession(draft);
  };

  const availabilityBadge =
    serviceState === "loading"
      ? { tone: "info" as const, label: "Checking Ask Penge status" }
      : serviceState === "error"
        ? { tone: "critical" as const, label: "Ask Penge status unavailable" }
        : serviceState === "ready" && featureEnabled && modelAvailable
          ? { tone: "good" as const, label: "Exact HydraFusion available" }
          : { tone: "critical" as const, label: "Exact HydraFusion unavailable" };

  const content = (
    <>
      <PageHeader
        title="Ask Penge"
        description="Evidence-first answers with visible tool progress, clear source freshness, and EUR/DKK context — no chain-of-thought leaks and no direct finance data access."
        badge={<Pill tone={availabilityBadge.tone}>{availabilityBadge.label}</Pill>}
      />

      <Panel
        eyebrow="Household Q&A"
        title="Streamed answer workbench"
        actions={
          <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap" }}>
            {isStreaming ? (
              <Button
                variant="contained"
                color="inherit"
                size="small"
                onClick={() => void stopSession()}
              >
                Stop
              </Button>
            ) : canAsk && streamState !== "idle" ? (
              <Button variant="contained" size="small" onClick={() => startSession(draft)}>
                Retry
              </Button>
            ) : (
              <Button variant="contained" size="small" disabled>
                Ask unavailable
              </Button>
            )}
          </Stack>
        }
      >
        <Stack spacing={2}>
          {serviceState === "loading" ? (
            <Alert severity="info" variant="outlined" sx={{ borderRadius: 2 }}>
              Checking the server-derived GitHub linkage, feature gate, and exact HydraFusion
              availability.
            </Alert>
          ) : serviceState === "error" ? (
            <Alert
              severity="error"
              variant="outlined"
              action={
                onRetryStatus ? (
                  <Button color="inherit" size="small" onClick={onRetryStatus}>
                    Retry status
                  </Button>
                ) : undefined
              }
              sx={{ borderRadius: 2 }}
            >
              <Box component="strong" sx={{ display: "block" }}>
                Ask Penge status is unavailable
              </Box>
              {serviceError ??
                "The trusted chat status could not be loaded. No request will be sent."}
            </Alert>
          ) : serviceState === "ready" && !featureEnabled ? (
            <Alert severity="warning" variant="outlined" sx={{ borderRadius: 2 }}>
              <Box component="strong" sx={{ display: "block" }}>
                Ask Penge is disabled by the service
              </Box>
              The backend feature gate is closed. No request will be sent.
            </Alert>
          ) : !modelAvailable ? (
            <Alert severity="warning" variant="outlined" sx={{ borderRadius: 2 }}>
              <Box component="strong" sx={{ display: "block" }}>
                Exact HydraFusion is unavailable
              </Box>
              The exact <Box component="code">hydrafusion</Box> entitlement is unavailable or the
              chat backend is not configured. Ask Penge will not send a request or substitute
              another model.
            </Alert>
          ) : null}

          <GitHubStatusCard
            authState={authState}
            login={githubLogin}
            onLink={onLinkGitHub}
            onUnlink={onUnlinkGitHub}
          />

          {contractError !== null ? (
            <Alert severity="error" variant="outlined" sx={{ borderRadius: 2 }}>
              <Box component="strong" sx={{ display: "block" }}>
                Unsupported answer stream
              </Box>
              {contractError}
            </Alert>
          ) : null}

          {streamError !== null ? (
            <Alert severity="error" variant="outlined" sx={{ borderRadius: 2 }}>
              <Box component="strong" sx={{ display: "block" }}>
                {streamErrorTitle(streamError)}
              </Box>
              <Box component="span" sx={{ display: "block", mt: 0.5 }}>
                {streamError.message}
              </Box>
            </Alert>
          ) : null}

          {streamState === "cancelled" ? (
            <Alert severity="info" variant="outlined" sx={{ borderRadius: 2 }}>
              Answer cancelled. The partial answer and its evidence remain visible until you retry.
            </Alert>
          ) : null}

          {streamState === "disconnected" ? (
            <Alert
              severity="warning"
              variant="outlined"
              action={
                <Button color="inherit" size="small" onClick={() => startSession(draft)}>
                  Reconnect
                </Button>
              }
              sx={{ borderRadius: 2 }}
            >
              Connection interrupted. Reconnect to start a new bounded session; no transcript was
              persisted.
            </Alert>
          ) : null}

          <Box
            sx={{
              display: "grid",
              gap: 2,
              minWidth: 0,
              gridTemplateColumns: {
                xs: "minmax(0, 1fr)",
                md: railCollapsed
                  ? "minmax(0, 1fr) auto"
                  : "minmax(0, 1.85fr) minmax(280px, 0.95fr)",
              },
              alignItems: "start",
            }}
          >
            <Paper
              variant="outlined"
              sx={{
                borderRadius: 3,
                p: { xs: 1.5, md: 2 },
                background: "background.default",
              }}
            >
              <Stack spacing={1.5}>
                <Stack
                  direction="row"
                  spacing={1}
                  sx={{ alignItems: "center", justifyContent: "space-between" }}
                >
                  <Typography variant="subtitle2" sx={{ fontWeight: 700, color: "text.secondary" }}>
                    Conversation
                  </Typography>
                  <Button
                    variant="outlined"
                    size="small"
                    onClick={() => setDrawerOpen(true)}
                    sx={{ display: { md: "none" } }}
                    aria-label={`Open evidence sheet, ${evidenceItems.length} items`}
                  >
                    Evidence ({evidenceItems.length})
                  </Button>
                </Stack>
                <List
                  disablePadding
                  aria-label="Conversation transcript"
                  sx={{ display: "flex", flexDirection: "column", gap: 1.5 }}
                >
                  {answer.length === 0 ? (
                    <ListItem disablePadding>
                      <Box
                        sx={{
                          width: "100%",
                          border: "1px dashed",
                          borderColor: "divider",
                          borderRadius: 2,
                          p: 2,
                          color: "text.secondary",
                        }}
                      >
                        {isStreaming
                          ? "Connecting to the bounded answer stream…"
                          : canAsk
                            ? "Ask a question to generate an evidence-first answer."
                            : "No request has been sent. Linkage, exact-model entitlement, and the bounded backend must be available first."}
                      </Box>
                    </ListItem>
                  ) : (
                    <ListItem disablePadding>
                      <Paper
                        variant="outlined"
                        sx={{
                          width: "100%",
                          minWidth: 0,
                          p: 1.5,
                          borderRadius: 2,
                          bgcolor: "background.paper",
                          borderColor: "rgba(45, 212, 191, 0.25)",
                          "@media (prefers-reduced-motion: reduce)": {
                            transition: "none",
                          },
                        }}
                      >
                        <Typography
                          role="status"
                          aria-live="polite"
                          aria-atomic="false"
                          sx={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", lineHeight: 1.6 }}
                        >
                          {answer}
                        </Typography>
                      </Paper>
                    </ListItem>
                  )}
                </List>

                <Box component="form" onSubmit={submitQuestion}>
                  <Stack spacing={1.25}>
                    <TextField
                      label="Ask Penge"
                      placeholder="Ask about balances, planning, or evidence coverage"
                      value={draft}
                      onChange={(event) => setDraft(event.target.value)}
                      slotProps={{ htmlInput: { maxLength: 8_000 } }}
                      multiline
                      minRows={3}
                      maxRows={6}
                      fullWidth
                      aria-label="Ask Penge message"
                      onKeyDown={(event) => {
                        if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
                          event.preventDefault();
                          event.currentTarget.closest("form")?.requestSubmit();
                        }
                      }}
                      helperText={
                        canAsk
                          ? "Press Ctrl+Enter or Command+Enter to ask."
                          : "Asking remains disabled until identity and exact-model availability are confirmed by the backend."
                      }
                      sx={{
                        "& .MuiInputBase-root": { minHeight: 96 },
                        "@media (prefers-reduced-motion: reduce)": { scrollBehavior: "auto" },
                      }}
                    />
                    <Stack
                      direction="row"
                      spacing={1}
                      sx={{ justifyContent: "flex-end", flexWrap: "wrap" }}
                    >
                      <Button type="button" variant="text" onClick={() => setDraft("")}>
                        Clear
                      </Button>
                      <Button
                        type="submit"
                        variant="contained"
                        disabled={!draft.trim() || isStreaming || !canAsk}
                      >
                        {isStreaming ? "Streaming…" : "Ask"}
                      </Button>
                    </Stack>
                  </Stack>
                </Box>
              </Stack>
            </Paper>

            {isMobile ? null : (
              <Paper
                component="aside"
                aria-label="Answer evidence"
                variant="outlined"
                sx={{
                  display: { xs: "none", md: "block" },
                  position: { md: "sticky" },
                  top: { md: 24 },
                  width: railCollapsed ? 52 : "auto",
                  borderRadius: 3,
                  p: railCollapsed ? 0.75 : 2,
                  background: "background.default",
                  overflow: "hidden",
                  "& > .MuiStack-root > :not(:first-of-type)": {
                    display: railCollapsed ? "none" : undefined,
                  },
                }}
              >
                <Stack spacing={2}>
                  <Stack
                    direction="row"
                    spacing={1}
                    sx={{ alignItems: "center", justifyContent: "space-between" }}
                  >
                    <Typography
                      variant="subtitle2"
                      sx={{ fontWeight: 700, color: "text.secondary" }}
                    >
                      {railCollapsed ? " " : "Evidence"}
                    </Typography>
                    <Button
                      variant="text"
                      size="small"
                      onClick={() => setRailCollapsed((current) => !current)}
                      aria-expanded={!railCollapsed}
                      aria-label={railCollapsed ? "Expand evidence rail" : "Collapse evidence rail"}
                      sx={{ minWidth: railCollapsed ? 36 : undefined, px: railCollapsed ? 0.5 : 1 }}
                    >
                      {railCollapsed ? "›" : "Collapse"}
                    </Button>
                  </Stack>

                  <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap" }}>
                    {FILTER_TABS.map((tab) => (
                      <Chip
                        key={tab.value}
                        label={tab.label}
                        clickable
                        color={activeFilter === tab.value ? "primary" : "default"}
                        variant={activeFilter === tab.value ? "filled" : "outlined"}
                        aria-pressed={activeFilter === tab.value}
                        onClick={() => setActiveFilter(tab.value)}
                      />
                    ))}
                  </Stack>

                  <Stack spacing={1.25}>
                    {toolEvents.length === 0 ? (
                      <Box
                        sx={{
                          border: "1px dashed",
                          borderColor: "divider",
                          borderRadius: 2,
                          p: 1.5,
                          color: "text.secondary",
                        }}
                      >
                        No tool progress yet.
                      </Box>
                    ) : (
                      toolEvents.map((event) => (
                        <Paper
                          key={event.id}
                          variant="outlined"
                          sx={{ borderRadius: 2, p: 1.25, bgcolor: "background.paper" }}
                        >
                          <Stack
                            direction="row"
                            spacing={1}
                            sx={{ alignItems: "center", justifyContent: "space-between" }}
                          >
                            <Typography sx={{ fontWeight: 700 }}>{event.name}</Typography>
                            <Pill tone={toolTone[event.status]}>{event.status}</Pill>
                          </Stack>
                          <Typography color="text.secondary" sx={{ mt: 0.5, fontSize: "0.86rem" }}>
                            {event.detail}
                          </Typography>
                        </Paper>
                      ))
                    )}
                  </Stack>

                  <Stack spacing={1.25}>
                    {selectedEvidence.length === 0 ? (
                      <Box
                        sx={{
                          border: "1px dashed",
                          borderColor: "divider",
                          borderRadius: 2,
                          p: 1.5,
                          color: "text.secondary",
                        }}
                      >
                        No evidence records yet.
                      </Box>
                    ) : (
                      selectedEvidence.map((event) => (
                        <Paper
                          key={event.id}
                          variant="outlined"
                          sx={{ borderRadius: 2, p: 1.5, bgcolor: "background.paper" }}
                        >
                          <Stack
                            direction="row"
                            spacing={1}
                            sx={{ alignItems: "center", justifyContent: "space-between" }}
                          >
                            <Typography sx={{ fontWeight: 700 }}>{event.title}</Typography>
                            <Pill tone={evidenceTone[event.coverage]}>{event.coverage}</Pill>
                          </Stack>
                          <Typography color="text.secondary" sx={{ mt: 0.5, fontSize: "0.82rem" }}>
                            {event.source}
                          </Typography>
                          <Stack direction="row" spacing={1} sx={{ mt: 1, flexWrap: "wrap" }}>
                            <Pill tone={freshnessTone[event.freshness]}>{event.freshness}</Pill>
                            <Pill tone="info">{event.currency}</Pill>
                          </Stack>
                          <Typography sx={{ mt: 1, fontSize: "0.87rem", whiteSpace: "pre-wrap" }}>
                            {event.summary}
                          </Typography>
                        </Paper>
                      ))
                    )}
                  </Stack>

                  {completion ? (
                    <Alert severity="success" variant="outlined" sx={{ borderRadius: 2 }}>
                      {completion.summary}
                    </Alert>
                  ) : null}

                  {completion?.assumptions.length ? (
                    <AssumptionsList assumptions={completion.assumptions} />
                  ) : null}

                  <Box
                    sx={{ border: "1px solid", borderColor: "divider", borderRadius: 2, p: 1.25 }}
                  >
                    <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
                      Account status
                    </Typography>
                    <Stack direction="row" spacing={1} sx={{ mt: 1, flexWrap: "wrap" }}>
                      <Pill tone="good">EUR + DKK evidence</Pill>
                      <Pill tone={authState === "linked" ? "good" : "watch"}>
                        {authState === "linked" ? "GitHub linked" : "GitHub not linked"}
                      </Pill>
                      <Pill tone={completion ? "good" : "info"}>
                        {completion ? "Answer ready" : "Awaiting answer"}
                      </Pill>
                    </Stack>
                    <Typography color="text.secondary" sx={{ mt: 1, fontSize: "0.82rem" }}>
                      Freshness is computed from the latest exact source timestamps; partial
                      coverage is surfaced explicitly so no answer hides a missing fact.
                    </Typography>
                  </Box>
                </Stack>
              </Paper>
            )}
          </Box>
        </Stack>
      </Panel>
    </>
  );

  return (
    <>
      {content}
      <Drawer
        anchor="bottom"
        open={isMobile && drawerOpen}
        onClose={() => setDrawerOpen(false)}
        ModalProps={{ keepMounted: false }}
        slotProps={{ paper: { sx: { maxHeight: "82dvh", overflowY: "auto" } } }}
      >
        <Box
          role="region"
          aria-label="Answer evidence sheet"
          sx={{ p: 2, pb: 3, borderTop: "1px solid", borderColor: "divider", minWidth: 0 }}
        >
          <Stack spacing={1.5}>
            <Stack
              direction="row"
              spacing={1}
              sx={{ justifyContent: "space-between", alignItems: "center" }}
            >
              <Typography variant="h6" sx={{ fontWeight: 700 }}>
                Evidence
              </Typography>
              <IconButton aria-label="Close evidence sheet" onClick={() => setDrawerOpen(false)}>
                ×
              </IconButton>
            </Stack>
            <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap" }}>
              {FILTER_TABS.map((tab) => (
                <Chip
                  key={tab.value}
                  label={tab.label}
                  clickable
                  color={activeFilter === tab.value ? "primary" : "default"}
                  variant={activeFilter === tab.value ? "filled" : "outlined"}
                  aria-pressed={activeFilter === tab.value}
                  onClick={() => setActiveFilter(tab.value)}
                />
              ))}
            </Stack>
            <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
              Tool activity
            </Typography>
            {toolEvents.length === 0 ? (
              <Typography color="text.secondary">No tool activity yet.</Typography>
            ) : (
              toolEvents.map((event) => (
                <Box
                  key={event.id}
                  sx={{ border: "1px solid", borderColor: "divider", borderRadius: 2, p: 1.5 }}
                >
                  <Stack
                    direction="row"
                    spacing={1}
                    sx={{ justifyContent: "space-between", alignItems: "center" }}
                  >
                    <Typography sx={{ fontWeight: 700 }}>{event.name}</Typography>
                    <Pill tone={toolTone[event.status]}>{event.status}</Pill>
                  </Stack>
                  <Typography color="text.secondary" sx={{ mt: 0.5, overflowWrap: "anywhere" }}>
                    {event.detail}
                  </Typography>
                </Box>
              ))
            )}
            <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
              Sources
            </Typography>
            {selectedEvidence.length === 0 ? (
              <Typography color="text.secondary">No evidence items yet.</Typography>
            ) : (
              selectedEvidence.map((event) => (
                <Box
                  key={event.id}
                  sx={{ border: "1px solid", borderColor: "divider", borderRadius: 2, p: 1.5 }}
                >
                  <Typography sx={{ fontWeight: 700 }}>{event.title}</Typography>
                  <Typography color="text.secondary" sx={{ fontSize: "0.82rem", mt: 0.5 }}>
                    {event.source}
                  </Typography>
                  <Stack direction="row" spacing={1} sx={{ mt: 1, flexWrap: "wrap" }}>
                    <Pill tone={evidenceTone[event.coverage]}>{event.coverage}</Pill>
                    <Pill tone={freshnessTone[event.freshness]}>{event.freshness}</Pill>
                    <Pill tone="info">{event.currency}</Pill>
                  </Stack>
                  <Typography sx={{ mt: 1 }}>{event.summary}</Typography>
                </Box>
              ))
            )}
            {completion ? (
              <Alert severity="success" variant="outlined">
                {completion.summary}
              </Alert>
            ) : null}
            {completion?.assumptions.length ? (
              <AssumptionsList assumptions={completion.assumptions} />
            ) : null}
          </Stack>
        </Box>
      </Drawer>
    </>
  );
}

function AssumptionsList({
  assumptions,
}: {
  readonly assumptions: readonly string[];
}): React.JSX.Element {
  return (
    <Box component="section" aria-labelledby="ask-penge-assumptions">
      <Typography id="ask-penge-assumptions" variant="subtitle2" sx={{ fontWeight: 700 }}>
        Assumptions and limits
      </Typography>
      <List dense disablePadding sx={{ mt: 0.5 }}>
        {assumptions.map((assumption) => (
          <ListItem key={assumption} disableGutters sx={{ alignItems: "flex-start", py: 0.25 }}>
            <Typography
              color="text.secondary"
              sx={{ overflowWrap: "anywhere", fontSize: "0.84rem" }}
            >
              • {assumption}
            </Typography>
          </ListItem>
        ))}
      </List>
    </Box>
  );
}

export function GitHubStatusCard({
  authState,
  login,
  onLink,
  onUnlink,
}: {
  readonly authState: AuthState;
  readonly login: string | null;
  readonly onLink: (() => void) | undefined;
  readonly onUnlink: (() => void) | undefined;
}): React.JSX.Element {
  return (
    <Paper variant="outlined" sx={{ borderRadius: 2, p: 1.5, bgcolor: "background.default" }}>
      <Stack spacing={1}>
        <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
          GitHub account
        </Typography>
        {authState === "linked" ? (
          <>
            <Typography color="text.secondary">
              {login === null ? "Linked GitHub account" : `Linked as @${login}`}. Credentials and
              quota are never shared.
            </Typography>
            {onUnlink ? (
              <Link component="button" type="button" onClick={onUnlink} sx={{ textAlign: "left" }}>
                Unlink GitHub account
              </Link>
            ) : null}
          </>
        ) : (
          <>
            <Typography color="text.secondary">
              {authState === "expired"
                ? "This GitHub authorization expired. Reauthenticate before a live bounded session."
                : authState === "not-configured"
                  ? "GitHub account linking is not configured. No local control can simulate a verified identity."
                  : "Connect your own account before asking for exact HydraFusion or Copilot-backed household answers."}
            </Typography>
            {onLink ? (
              <Link component="button" type="button" onClick={onLink} sx={{ textAlign: "left" }}>
                {authState === "expired" ? "Reauthenticate GitHub account" : "Link GitHub account"}
              </Link>
            ) : (
              <Button variant="outlined" size="small" disabled sx={{ alignSelf: "flex-start" }}>
                GitHub linking unavailable
              </Button>
            )}
          </>
        )}
      </Stack>
    </Paper>
  );
}
