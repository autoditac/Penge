import type {
  AskRequest,
  AskStreamEvent,
  AskStreamTextEvent,
  AskTransport,
  AskTransportSession,
} from "./contract";

export const defaultAskStream: ReadonlyArray<AskStreamEvent> = [
  {
    type: "tool",
    id: "tool-1",
    name: "HydraFusion exact review",
    status: "started",
    detail: "Confirming the exact data path and freshness window.",
    startedAt: new Date().toISOString(),
  },
  {
    type: "tool",
    id: "tool-2",
    name: "DKK + EUR evidence pull",
    status: "running",
    detail: "Collecting the latest household balances and source timestamps.",
    startedAt: new Date().toISOString(),
  },
  {
    type: "text",
    id: "text-1",
    stream: "answer",
    delta:
      "I checked the latest household balances and the main risk is in the upcoming tax-planning window. The portfolio remains broadly healthy, but the pension and cash buffers still need one more review.",
    source: "assistant",
  },
  {
    type: "evidence",
    id: "evidence-1",
    title: "Net worth snapshot",
    source: "HydraFusion exact data",
    coverage: "full",
    freshness: "fresh",
    currency: "mixed",
    summary: "DKK 1.42M and EUR 194k, refreshed 18 minutes ago.",
  },
  {
    type: "evidence",
    id: "evidence-2",
    title: "Tax planning items",
    source: "Household rules + holdings",
    coverage: "partial",
    freshness: "fresh",
    currency: "EUR",
    summary:
      "Two flagged items are due before the year-end cut-off; no values were estimated from outside source data.",
  },
  {
    type: "tool",
    id: "tool-3",
    name: "Source coverage check",
    status: "complete",
    detail:
      "Coverage is complete for the visible balances, with one partial item on tax assumptions.",
    startedAt: new Date().toISOString(),
  },
  {
    type: "text",
    id: "text-2",
    stream: "answer",
    delta:
      "The safe next step is to review the DKK cash buffers, confirm the tax assumptions, and keep the evidence links visible before any change in the plan.",
    source: "assistant",
  },
  {
    type: "completion",
    id: "complete-1",
    summary: "Answer ready with fresh evidence and bounded sources.",
    coverage: "partial",
    freshness: "fresh",
  },
] as const satisfies ReadonlyArray<AskStreamEvent>;

export function createMockAskTransport(
  events: ReadonlyArray<AskStreamEvent> = defaultAskStream,
): AskTransport {
  return {
    start(request: AskRequest): AskTransportSession {
      let active = true;
      let index = 0;
      const listeners = new Set<(event: AskStreamEvent) => void>();

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
          setTimeout(emitNext, 260);
        }
      };

      const session: AskTransportSession = {
        stop: () => {
          active = false;
        },
        retry: () => {
          active = true;
          index = 0;
          emitNext();
        },
        subscribe: (callback) => {
          listeners.add(callback);
          return () => {
            listeners.delete(callback);
          };
        },
      };

      if (request.question.trim().length > 0) {
        emitNext();
      }

      return session;
    },
  };
}

export function buildTextEvent(delta: string): AskStreamTextEvent {
  return {
    type: "text",
    id: `text-${Math.random().toString(36).slice(2, 8)}`,
    stream: "answer",
    delta,
    source: "assistant",
  };
}
