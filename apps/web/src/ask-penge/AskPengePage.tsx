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
  AskStreamTextEvent,
  AskStreamToolEvent,
  AskTransport,
  AskTransportSession,
} from "./contract";
import { createMockAskTransport } from "./mockTransport";

type FilterValue = "all" | "last-30d" | "quarter";
type AuthState = "linked" | "not-linked" | "unavailable";

type AskPengePageProps = {
  readonly transport?: AskTransport;
};

const FILTER_TABS: ReadonlyArray<{ value: FilterValue; label: string }> = [
  { value: "all", label: "All" },
  { value: "last-30d", label: "30 days" },
  { value: "quarter", label: "Quarter" },
] as const;

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

const defaultAskTransport = createMockAskTransport();

export function AskPengePage({
  transport = defaultAskTransport,
}: AskPengePageProps): React.JSX.Element {
  return <AskPengeWorkbench transport={transport} />;
}

function AskPengeWorkbench({ transport }: { readonly transport: AskTransport }): React.JSX.Element {
  const [events, setEvents] = useState<readonly AskStreamEvent[]>([]);
  const [draft, setDraft] = useState<string>(
    "Which balances and tax-check items need a fresh review before the next quarter?",
  );
  const [isStreaming, setIsStreaming] = useState<boolean>(true);
  const [activeFilter, setActiveFilter] = useState<FilterValue>("all");
  const [authState, setAuthState] = useState<AuthState>("not-linked");
  const [drawerOpen, setDrawerOpen] = useState<boolean>(false);
  const [streamError, setStreamError] = useState<AskStreamErrorEvent | null>(null);
  const sessionRef = useRef<AskTransportSession | null>(null);
  const unsubscribeRef = useRef<(() => void) | null>(null);
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("md"));

  useEffect(() => {
    if (sessionRef.current !== null) {
      return;
    }

    void startSession(
      "Which balances and tax-check items need a fresh review before the next quarter?",
    );
  }, [transport]);

  function stopSession(): void {
    sessionRef.current?.stop();
    setIsStreaming(false);
    if (unsubscribeRef.current !== null) {
      unsubscribeRef.current();
      unsubscribeRef.current = null;
    }
  }

  function startSession(question: string): void {
    if (!question.trim()) {
      return;
    }

    if (sessionRef.current !== null) {
      sessionRef.current.stop();
    }
    if (unsubscribeRef.current !== null) {
      unsubscribeRef.current();
    }

    const nextSession = transport.start({ question: question.trim(), memberId: "current-member" });
    sessionRef.current = nextSession;
    setIsStreaming(true);
    setStreamError(null);

    unsubscribeRef.current = nextSession.subscribe((event) => {
      setEvents((previous) => [...previous, event]);
      if (event.type === "error") {
        setStreamError(event);
        setIsStreaming(false);
      }
      if (event.type === "completion") {
        setIsStreaming(false);
      }
    });
  }

  const evidenceItems = useMemo(
    () => events.filter((event): event is AskStreamEvidenceEvent => event.type === "evidence"),
    [events],
  );

  const toolEvents = useMemo(
    () => events.filter((event): event is AskStreamToolEvent => event.type === "tool"),
    [events],
  );

  const textEvents = useMemo(
    () => events.filter((event): event is AskStreamTextEvent => event.type === "text"),
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

    if (activeFilter === "last-30d") {
      return evidenceItems.filter((item) => item.freshness === "fresh");
    }

    return evidenceItems.filter((item) => item.currency === "mixed" || item.coverage === "partial");
  }, [activeFilter, evidenceItems]);

  const selectedEvidence = visibleEvidence.length > 0 ? visibleEvidence : evidenceItems;

  const submitQuestion = (event: React.FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    if (!draft.trim()) {
      return;
    }
    startSession(draft);
  };

  const content = (
    <>
      <PageHeader
        title="Ask Penge"
        description="Evidence-first answers with visible tool progress, clear source freshness, and EUR/DKK context — no chain-of-thought leaks and no direct finance data access."
        badge={
          <Pill tone={authState === "linked" ? "good" : "watch"}>
            {authState === "linked" ? "GitHub linked" : "GitHub account required"}
          </Pill>
        }
      />

      <Panel
        eyebrow="Household Q&A"
        title="Streamed answer workbench"
        actions={
          <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap" }}>
            <Button
              variant="outlined"
              size="small"
              onClick={() =>
                setAuthState((current) => (current === "linked" ? "not-linked" : "linked"))
              }
            >
              {authState === "linked" ? "Unlink GitHub" : "Link GitHub"}
            </Button>
            {isStreaming ? (
              <Button variant="contained" color="inherit" size="small" onClick={stopSession}>
                Stop
              </Button>
            ) : (
              <Button variant="contained" size="small" onClick={() => startSession(draft)}>
                Retry
              </Button>
            )}
          </Stack>
        }
      >
        <Stack spacing={2}>
          {authState === "unavailable" ? (
            <Alert severity="warning" variant="outlined" sx={{ borderRadius: 2 }}>
              HydraFusion exact review is unavailable for this household. Ask Penge remains
              read-only and evidence-first until the exact entitlement is verified.
            </Alert>
          ) : null}

          {streamError !== null ? (
            <Alert severity="error" variant="outlined" sx={{ borderRadius: 2 }}>
              <Box component="strong" sx={{ display: "block" }}>
                {streamError.code === "auth_expired"
                  ? "GitHub session expired"
                  : streamError.code === "hydrafusion_unavailable"
                    ? "Exact HydraFusion data is unavailable"
                    : "This answer could not be completed"}
              </Box>
              <Box component="span" sx={{ display: "block", mt: 0.5 }}>
                {streamError.message}
              </Box>
            </Alert>
          ) : null}

          <Box
            sx={{
              display: "grid",
              gap: 2,
              gridTemplateColumns: { xs: "1fr", lg: "minmax(0, 1.85fr) minmax(240px, 0.95fr)" },
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
                <Typography variant="subtitle2" sx={{ fontWeight: 700, color: "text.secondary" }}>
                  Conversation
                </Typography>
                <List disablePadding sx={{ display: "flex", flexDirection: "column", gap: 1.5 }}>
                  {textEvents.length === 0 ? (
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
                        Ask a question to generate an evidence-first answer.
                      </Box>
                    </ListItem>
                  ) : (
                    textEvents.map((event) => (
                      <ListItem key={event.id} disablePadding>
                        <Paper
                          variant="outlined"
                          sx={{
                            width: "100%",
                            p: 1.5,
                            borderRadius: 2,
                            bgcolor: "background.paper",
                            borderColor: "rgba(45, 212, 191, 0.25)",
                            "@media (prefers-reduced-motion: reduce)": {
                              transition: "none",
                            },
                          }}
                        >
                          <Typography sx={{ whiteSpace: "pre-wrap", lineHeight: 1.6 }}>
                            {event.delta}
                          </Typography>
                        </Paper>
                      </ListItem>
                    ))
                  )}
                </List>

                <Box component="form" onSubmit={submitQuestion}>
                  <Stack spacing={1.25}>
                    <TextField
                      label="Ask Penge"
                      placeholder="Ask about balances, planning, or evidence coverage"
                      value={draft}
                      onChange={(event) => setDraft(event.target.value)}
                      multiline
                      minRows={3}
                      maxRows={6}
                      fullWidth
                      aria-label="Ask Penge message"
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
                        disabled={!draft.trim() || isStreaming}
                      >
                        {isStreaming ? "Streaming…" : "Ask"}
                      </Button>
                    </Stack>
                  </Stack>
                </Box>
              </Stack>
            </Paper>

            <Paper
              variant="outlined"
              sx={{
                position: { lg: "sticky" },
                top: { lg: 24 },
                borderRadius: 3,
                p: { xs: 1.5, md: 2 },
                background: "background.default",
              }}
            >
              <Stack spacing={2}>
                <Stack
                  direction="row"
                  spacing={1}
                  sx={{ alignItems: "center", justifyContent: "space-between" }}
                >
                  <Typography variant="subtitle2" sx={{ fontWeight: 700, color: "text.secondary" }}>
                    Evidence
                  </Typography>
                  <Button
                    variant="text"
                    size="small"
                    onClick={() => setDrawerOpen(true)}
                    sx={{ display: { md: "none" } }}
                  >
                    Open
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

                <Box sx={{ border: "1px solid", borderColor: "divider", borderRadius: 2, p: 1.25 }}>
                  <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
                    Account status
                  </Typography>
                  <Stack direction="row" spacing={1} sx={{ mt: 1, flexWrap: "wrap" }}>
                    <Pill tone="good">EUR + DKK evidence</Pill>
                    <Pill tone={authState === "linked" ? "good" : "watch"}>
                      {authState === "linked" ? "GitHub verified" : "GitHub not linked"}
                    </Pill>
                    <Pill tone={completion ? "good" : "info"}>
                      {completion ? "Answer ready" : "Awaiting answer"}
                    </Pill>
                  </Stack>
                  <Typography color="text.secondary" sx={{ mt: 1, fontSize: "0.82rem" }}>
                    Freshness is computed from the latest exact source timestamps; partial coverage
                    is surfaced explicitly so no answer hides a missing fact.
                  </Typography>
                </Box>
              </Stack>
            </Paper>
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
      >
        <Box sx={{ p: 2, pb: 3, borderTop: "1px solid", borderColor: "divider" }}>
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
                  <Typography sx={{ mt: 1 }}>{event.summary}</Typography>
                </Box>
              ))
            )}
          </Stack>
        </Box>
      </Drawer>
    </>
  );
}

export function GitHubStatusCard({
  authState,
  onLink,
}: {
  readonly authState: AuthState;
  readonly onLink: () => void;
}): React.JSX.Element {
  return (
    <Paper variant="outlined" sx={{ borderRadius: 2, p: 1.5, bgcolor: "background.default" }}>
      <Stack spacing={1}>
        <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
          GitHub account
        </Typography>
        {authState === "linked" ? (
          <Typography color="text.secondary">Linked to the current household member.</Typography>
        ) : (
          <>
            <Typography color="text.secondary">
              Connect an account before asking for exact HydraFusion or Copilot-backed household
              answers.
            </Typography>
            <Link component="button" type="button" onClick={onLink} sx={{ textAlign: "left" }}>
              Link GitHub account
            </Link>
          </>
        )}
      </Stack>
    </Paper>
  );
}
