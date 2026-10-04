/** Component tests for the Ask Penge workbench.
 * @vitest-environment jsdom
 */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AskPengePage } from "../src/ask-penge/AskPengePage";
import {
  ASK_STREAM_PROTOCOL_VERSION,
  askStreamEventSchema,
  createAskStreamValidator,
} from "../src/ask-penge/contract";
import type { AskRequest, AskStreamEvent, AskTransport } from "../src/ask-penge/contract";

const useMediaQueryMock = vi.fn();

vi.mock("@mui/material/useMediaQuery", () => ({
  default: () => useMediaQueryMock(),
}));

function envelope(sequence: number): {
  version: typeof ASK_STREAM_PROTOCOL_VERSION;
  sessionId: string;
  sequence: number;
} {
  return {
    version: ASK_STREAM_PROTOCOL_VERSION,
    sessionId: "synthetic-test-session",
    sequence,
  };
}

function createTransport(events: ReadonlyArray<AskStreamEvent>): AskTransport {
  return {
    start() {
      let index = 0;
      const listeners = new Set<(event: unknown) => void>();

      const emitNext = (): void => {
        const event = events[index];
        if (event === undefined) {
          return;
        }

        index += 1;
        for (const listener of listeners) {
          listener(event);
        }
        if (index < events.length) {
          setTimeout(emitNext, 25);
        }
      };

      return {
        stop: () => {
          index = events.length;
        },
        subscribe: (callback) => {
          listeners.add(callback);
          setTimeout(emitNext, 0);
          return () => {
            listeners.delete(callback);
          };
        },
      };
    },
  };
}

function createImmediateTransport(events: ReadonlyArray<AskStreamEvent>): AskTransport {
  return {
    start() {
      let active = true;
      return {
        stop: () => {
          active = false;
        },
        subscribe: (callback) => {
          if (active) {
            for (const event of events) {
              if (!active) {
                break;
              }
              callback(event);
            }
          }
          return () => {
            active = false;
          };
        },
      };
    },
  };
}

async function startInjectedStream(): Promise<void> {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Ask" }));
}

describe("AskPengePage", () => {
  beforeEach(() => {
    useMediaQueryMock.mockReturnValue(true);
  });

  it("renders an injected stream and allows cancelling the bounded session", async () => {
    render(
      <AskPengePage
        authState="linked"
        modelAvailable
        transport={createTransport([
          {
            ...envelope(0),
            type: "tool",
            id: "tool-1",
            name: "Synthetic Penge report lookup",
            status: "started",
            detail: "Reading synthetic report metadata.",
            startedAt: "2026-10-04T08:00:00.000Z",
          },
          {
            ...envelope(1),
            type: "text",
            id: "text-1",
            stream: "answer",
            delta: "The synthetic household balance looks stable.",
            source: "assistant",
          },
          {
            ...envelope(2),
            type: "evidence",
            id: "evidence-1",
            title: "Net worth snapshot",
            source: "Synthetic Penge net-worth report",
            coverage: "full",
            freshness: "fresh",
            currency: "mixed",
            summary: "Synthetic DKK 1.42M and EUR 194k, refreshed 18 minutes ago.",
          },
        ])}
      />,
    );

    await startInjectedStream();
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent("synthetic household balance"),
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Open evidence sheet/i }));
    expect(screen.getByText("Synthetic Penge report lookup")).toBeInTheDocument();
    expect(screen.getByText(/Synthetic DKK 1\.42M and EUR 194k/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Close evidence sheet" }));
    await waitFor(() =>
      expect(
        screen.queryByRole("region", { name: "Answer evidence sheet" }),
      ).not.toBeInTheDocument(),
    );

    await user.click(screen.getByRole("button", { name: "Stop" }));
    expect(screen.getByText(/Answer cancelled/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("surfaces exact-model failures without inventing a complete answer", async () => {
    render(
      <AskPengePage
        authState="linked"
        modelAvailable
        transport={createTransport([
          {
            ...envelope(0),
            type: "error",
            id: "error-1",
            code: "hydrafusion_unavailable",
            message: "Exact HydraFusion is unavailable for this linked identity.",
            retryable: false,
          },
        ])}
      />,
    );

    await startInjectedStream();
    await waitFor(() =>
      expect(screen.getByText("Exact HydraFusion data is unavailable")).toBeInTheDocument(),
    );
    expect(
      screen.getByText("Exact HydraFusion is unavailable for this linked identity."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("rejects unknown protocol versions and extra event fields", () => {
    expect(() =>
      askStreamEventSchema.parse({
        ...envelope(0),
        version: "2.0",
        type: "text",
        id: "bad",
        stream: "answer",
        delta: "Synthetic",
        source: "assistant",
      }),
    ).toThrow();

    expect(() =>
      askStreamEventSchema.parse({
        ...envelope(0),
        type: "text",
        id: "bad-extra-field",
        stream: "answer",
        delta: "Synthetic answer",
        source: "assistant",
        rawToolJson: { secret: true },
      }),
    ).toThrow();
  });

  it("stops and unsubscribes when a malformed runtime event crosses the adapter", async () => {
    let stopped = false;
    let unsubscribed = false;
    const transport: AskTransport = {
      start() {
        return {
          stop: () => {
            stopped = true;
          },
          subscribe: (callback) => {
            callback({ type: "text", version: "2.0" });
            return () => {
              unsubscribed = true;
            };
          },
        };
      },
    };
    render(<AskPengePage authState="linked" modelAvailable transport={transport} />);

    await startInjectedStream();
    expect(await screen.findByText("Unsupported answer stream")).toBeInTheDocument();
    await waitFor(() => expect(unsubscribed).toBe(true));
    expect(stopped).toBe(true);
  });

  it("collapses the desktop evidence rail without removing the transcript", async () => {
    useMediaQueryMock.mockReturnValue(false);
    render(<AskPengePage />);

    const user = userEvent.setup();
    expect(screen.getByRole("complementary", { name: "Answer evidence" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Collapse evidence rail" }));
    expect(screen.getByRole("button", { name: "Expand evidence rail" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(screen.getByLabelText("Conversation transcript")).toBeInTheDocument();
  });

  it("offers reconnect after an interrupted injected session", async () => {
    render(
      <AskPengePage
        authState="linked"
        modelAvailable
        transport={createTransport([
          {
            ...envelope(0),
            type: "error",
            id: "error-disconnected",
            code: "session_interrupted",
            message: "The bounded session disconnected.",
            retryable: true,
          },
        ])}
      />,
    );

    await startInjectedStream();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Reconnect" })).toBeInTheDocument(),
    );
    expect(screen.getByText(/no transcript was persisted/i)).toBeInTheDocument();
  });

  it.each([
    ["auth_expired", "GitHub session expired"],
    ["rate_limit", "Copilot rate limit reached"],
    ["data_missing", "Required source data is missing"],
    ["missing_fx", "EUR/DKK FX evidence is missing"],
    ["tool_timeout", "Evidence lookup timed out"],
  ] as const)("renders the %s recovery state", async (code, title) => {
    render(
      <AskPengePage
        authState="linked"
        modelAvailable
        transport={createImmediateTransport([
          {
            ...envelope(0),
            type: "error",
            id: `error-${code}`,
            code,
            message: `Synthetic ${code} recovery message.`,
            retryable: true,
          },
        ])}
      />,
    );

    await startInjectedStream();
    expect(await screen.findByText(title)).toBeInTheDocument();
    expect(screen.getByText(`Synthetic ${code} recovery message.`)).toBeInTheDocument();
  });

  it("buffers answer announcements and flushes them when cancelled", async () => {
    vi.useFakeTimers();
    try {
      const { unmount } = render(
        <AskPengePage
          authState="linked"
          modelAvailable
          transport={createImmediateTransport([
            {
              ...envelope(0),
              type: "text",
              id: "buffered-1",
              stream: "answer",
              delta: "Buffered ",
              source: "assistant",
            },
            {
              ...envelope(1),
              type: "text",
              id: "buffered-2",
              stream: "answer",
              delta: "answer.",
              source: "assistant",
            },
          ])}
        />,
      );
      fireEvent.click(screen.getByRole("button", { name: "Ask" }));
      expect(screen.queryByRole("status")).not.toBeInTheDocument();
      act(() => vi.advanceTimersByTime(119));
      expect(screen.queryByRole("status")).not.toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: "Stop" }));
      expect(screen.getByRole("status")).toHaveTextContent("Buffered answer.");
      expect(vi.getTimerCount()).toBe(0);
      unmount();

      const timed = render(
        <AskPengePage
          authState="linked"
          modelAvailable
          transport={createImmediateTransport([
            {
              ...envelope(0),
              type: "text",
              id: "timed-buffer",
              stream: "answer",
              delta: "Timed flush.",
              source: "assistant",
            },
          ])}
        />,
      );
      fireEvent.click(screen.getByRole("button", { name: "Ask" }));
      act(() => vi.advanceTimersByTime(120));
      expect(screen.getByRole("status")).toHaveTextContent("Timed flush.");
      timed.unmount();

      const pending = render(
        <AskPengePage
          authState="linked"
          modelAvailable
          transport={createImmediateTransport([
            {
              ...envelope(0),
              type: "text",
              id: "unmount-buffer",
              stream: "answer",
              delta: "Unmount flush.",
              source: "assistant",
            },
          ])}
        />,
      );
      fireEvent.click(screen.getByRole("button", { name: "Ask" }));
      expect(vi.getTimerCount()).toBeGreaterThan(0);
      pending.unmount();
      expect(vi.getTimerCount()).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it("flushes buffered text and renders typed assumptions on completion", async () => {
    render(
      <AskPengePage
        authState="linked"
        modelAvailable
        transport={createImmediateTransport([
          {
            ...envelope(0),
            type: "text",
            id: "terminal-text",
            stream: "answer",
            delta: "Terminal answer.",
            source: "assistant",
          },
          {
            ...envelope(1),
            type: "completion",
            id: "terminal-completion",
            summary: "Synthetic answer complete.",
            coverage: "partial",
            freshness: "fresh",
            finishReason: "completed",
            assumptions: ["Synthetic timestamps are treated as current."],
          },
        ])}
      />,
    );

    await startInjectedStream();
    expect(screen.getByRole("status")).toHaveTextContent("Terminal answer.");
    await userEvent.click(screen.getByRole("button", { name: /Open evidence sheet/i }));
    expect(screen.getByText("Assumptions and limits")).toBeInTheDocument();
    expect(screen.getByText(/Synthetic timestamps are treated as current/)).toBeInTheDocument();
  });

  it("fails closed without starting transport or simulating GitHub linkage", () => {
    const start = vi.fn((_request: AskRequest) =>
      createTransport([]).start({ question: "unused" }),
    );
    const transport: AskTransport = { start };

    render(<AskPengePage transport={transport} />);

    expect(start).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "GitHub linking unavailable" })).toBeDisabled();
    expect(screen.queryByText(/DKK 1\.42M/)).not.toBeInTheDocument();
  });

  it("never sends a browser-selected member identity", async () => {
    let request: AskRequest | undefined;
    const transport: AskTransport = {
      start(nextRequest) {
        request = nextRequest;
        return createTransport([]).start(nextRequest);
      },
    };
    render(<AskPengePage authState="linked" modelAvailable transport={transport} />);

    await startInjectedStream();

    expect(request).toEqual({
      question: "Which balances and tax-check items need a fresh review before the next quarter?",
    });
    expect(request).not.toHaveProperty("memberId");
  });

  it("rejects gaps, cross-session events, and events after a terminal event", () => {
    const text = {
      ...envelope(0),
      type: "text" as const,
      id: "text-ordered",
      stream: "answer" as const,
      delta: "Synthetic answer",
      source: "assistant" as const,
    };
    const gap = createAskStreamValidator();
    expect(gap(text)).toEqual(text);
    expect(() => gap({ ...text, id: "gap", sequence: 2 })).toThrow(/sequence 1/i);

    const crossSession = createAskStreamValidator();
    crossSession(text);
    expect(() =>
      crossSession({ ...text, id: "cross-session", sequence: 1, sessionId: "other-session" }),
    ).toThrow(/different session/i);

    const terminal = createAskStreamValidator();
    terminal({
      ...envelope(0),
      type: "completion",
      id: "complete",
      summary: "Done",
      coverage: "full",
      freshness: "fresh",
      finishReason: "completed",
      assumptions: [],
    });
    expect(() => terminal({ ...text, sequence: 1 })).toThrow(/after the stream terminated/i);
  });
});
