import type {
  AskRequest,
  AskStreamEvent,
  AskStreamTextEvent,
  AskTransport,
  AskTransportSession,
} from "./contract";
import { ASK_STREAM_PROTOCOL_VERSION } from "./contract";

const syntheticSessionId = "synthetic-session-ask-penge";
const syntheticTimestamp = "2026-10-04T08:00:00.000Z";

export const defaultAskStream: ReadonlyArray<AskStreamEvent> = [
  {
    version: ASK_STREAM_PROTOCOL_VERSION,
    sessionId: syntheticSessionId,
    sequence: 0,
    type: "tool",
    id: "tool-1",
    name: "Synthetic Penge report lookup",
    status: "started",
    detail: "Reading synthetic report metadata and its freshness window.",
    startedAt: syntheticTimestamp,
  },
  {
    version: ASK_STREAM_PROTOCOL_VERSION,
    sessionId: syntheticSessionId,
    sequence: 1,
    type: "tool",
    id: "tool-2",
    name: "Synthetic currency evidence lookup",
    status: "running",
    detail: "Collecting the latest household balances and source timestamps.",
    startedAt: syntheticTimestamp,
  },
  {
    version: ASK_STREAM_PROTOCOL_VERSION,
    sessionId: syntheticSessionId,
    sequence: 2,
    type: "text",
    id: "text-1",
    stream: "answer",
    delta:
      "I checked the latest household balances and the main risk is in the upcoming tax-planning window. The portfolio remains broadly healthy, but the pension and cash buffers still need one more review.",
    source: "assistant",
  },
  {
    version: ASK_STREAM_PROTOCOL_VERSION,
    sessionId: syntheticSessionId,
    sequence: 3,
    type: "evidence",
    id: "evidence-1",
    title: "Net worth snapshot",
    source: "Synthetic Penge net-worth report",
    coverage: "full",
    freshness: "fresh",
    currency: "mixed",
    summary: "DKK 1.42M and EUR 194k, refreshed 18 minutes ago.",
  },
  {
    version: ASK_STREAM_PROTOCOL_VERSION,
    sessionId: syntheticSessionId,
    sequence: 4,
    type: "evidence",
    id: "evidence-2",
    title: "Tax planning items",
    source: "Synthetic Penge planning report",
    coverage: "partial",
    freshness: "fresh",
    currency: "EUR",
    summary:
      "Two flagged items are due before the year-end cut-off; no values were estimated from outside source data.",
  },
  {
    version: ASK_STREAM_PROTOCOL_VERSION,
    sessionId: syntheticSessionId,
    sequence: 5,
    type: "tool",
    id: "tool-3",
    name: "Synthetic Penge source coverage",
    status: "complete",
    detail:
      "Coverage is complete for the visible balances, with one partial item on tax assumptions.",
    startedAt: syntheticTimestamp,
  },
  {
    version: ASK_STREAM_PROTOCOL_VERSION,
    sessionId: syntheticSessionId,
    sequence: 6,
    type: "text",
    id: "text-2",
    stream: "answer",
    delta:
      "The safe next step is to review the DKK cash buffers, confirm the tax assumptions, and keep the evidence links visible before any change in the plan.",
    source: "assistant",
  },
  {
    version: ASK_STREAM_PROTOCOL_VERSION,
    sessionId: syntheticSessionId,
    sequence: 7,
    type: "completion",
    id: "complete-1",
    summary: "Answer ready with fresh evidence and bounded sources.",
    coverage: "partial",
    freshness: "fresh",
    finishReason: "completed",
    assumptions: [
      "Synthetic report timestamps are treated as current for this test-only transport.",
      "No uncited value is used to fill a missing source.",
    ],
  },
] as const satisfies ReadonlyArray<AskStreamEvent>;

export function createMockAskTransport(
  events: ReadonlyArray<AskStreamEvent> = defaultAskStream,
): AskTransport {
  return {
    start(request: AskRequest): AskTransportSession {
      let active = true;
      let index = 0;
      let timer: ReturnType<typeof setTimeout> | null = null;
      const listeners = new Set<(event: unknown) => void>();

      const emitNext = (): void => {
        if (!active || index >= events.length) {
          return;
        }

        const event = events[index];
        if (event === undefined) {
          return;
        }

        index += 1;
        for (const listener of listeners) {
          listener(event);
        }

        if (index < events.length) {
          timer = setTimeout(emitNext, 260);
        }
      };

      const session: AskTransportSession = {
        stop: async () => {
          active = false;
          if (timer !== null) {
            clearTimeout(timer);
          }
        },
        close: () => {
          active = false;
          if (timer !== null) {
            clearTimeout(timer);
          }
        },
        subscribe: (callback) => {
          listeners.add(callback);
          if (request.question.trim().length > 0 && index === 0) {
            timer = setTimeout(emitNext, 0);
          }
          return () => {
            listeners.delete(callback);
          };
        },
      };

      return session;
    },
  };
}

export function buildTextEvent(delta: string): AskStreamTextEvent {
  return {
    version: ASK_STREAM_PROTOCOL_VERSION,
    sessionId: syntheticSessionId,
    sequence: 0,
    type: "text",
    id: `text-${Math.random().toString(36).slice(2, 8)}`,
    stream: "answer",
    delta,
    source: "assistant",
  };
}
