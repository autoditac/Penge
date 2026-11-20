/** Component tests for the Ask Penge workbench.
 * @vitest-environment jsdom
 */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AskPengePage } from "../src/ask-penge/AskPengePage";
import { AskPengeLivePage } from "../src/ask-penge/AskPengeLivePage";
import {
  ASK_STREAM_PROTOCOL_VERSION,
  askStreamEventSchema,
  createAskStreamValidator,
} from "../src/ask-penge/contract";
import type { AskRequest, AskStreamEvent, AskTransport } from "../src/ask-penge/contract";
import type { FetchLike } from "../src/ask-penge/liveClient";

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
        stop: async () => {
          index = events.length;
        },
        close: () => {
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
        stop: async () => {
          active = false;
        },
        close: () => {
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

  it.each([true, false])(
    "labels the exact model as experimental when availability is %s",
    (modelAvailable) => {
      render(
        <AskPengePage
          authState="linked"
          modelAvailable={modelAvailable}
          transport={createImmediateTransport([])}
        />,
      );

      expect(screen.getByText("Copilot Fusion (experimental · hydrafusion)")).toBeVisible();
    },
  );

  it("does not restore linked status from a stale refresh after unlinking", async () => {
    let resolveStaleStatus!: (response: Response) => void;
    const staleStatus = new Promise<Response>((resolve) => {
      resolveStaleStatus = resolve;
    });
    let statusCalls = 0;
    const linkedStatus = {
      github: { state: "linked" as const, login: "synthetic-user" },
      model: { id: "hydrafusion" as const, available: true },
      featureEnabled: true,
    };
    const notLinkedStatus = {
      github: { state: "not-linked" as const, login: null },
      model: { id: "hydrafusion" as const, available: true },
      featureEnabled: true,
    };
    const fetchFn: FetchLike = vi.fn(async (input, init) => {
      const url = new URL(String(input));
      const method = init?.method ?? "GET";
      if (url.pathname.endsWith("/v1/auth/status")) {
        statusCalls += 1;
        if (statusCalls === 1) {
          return Response.json(linkedStatus);
        }
        if (statusCalls === 2) {
          return staleStatus;
        }
        return Response.json(notLinkedStatus);
      }
      if (url.pathname.endsWith("/v1/auth/github") && method === "DELETE") {
        return Response.json({ status: "unlinked" });
      }
      if (url.pathname.endsWith("/v1/chat") && method === "POST") {
        const event = {
          version: ASK_STREAM_PROTOCOL_VERSION,
          sessionId: "synthetic-live-session",
          id: "expired",
          sequence: 0,
          type: "error",
          code: "auth_expired",
          message: "Synthetic expired authorization.",
          retryable: false,
        };
        return new Response(`data: ${JSON.stringify(event)}\n\n`, {
          headers: { "Content-Type": "text/event-stream" },
        });
      }
      throw new Error(`Unexpected synthetic request: ${method} ${url.pathname}`);
    });

    render(<AskPengeLivePage configuredBaseUrl="/chat" fetchFn={fetchFn} />);
    await screen.findByRole("button", { name: "Ask" });
    await userEvent.setup().click(screen.getByRole("button", { name: "Ask" }));
    await screen.findByText("GitHub session expired");
    await waitFor(() => expect(statusCalls).toBe(2));

    await userEvent.setup().click(screen.getByRole("button", { name: "Unlink GitHub account" }));
    await screen.findByRole("button", { name: "Link GitHub account" });
    await act(async () => {
      resolveStaleStatus(Response.json(linkedStatus));
      await staleStatus;
    });

    expect(screen.queryByRole("button", { name: "Unlink GitHub account" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Link GitHub account" })).toBeInTheDocument();
  });

  it("renders an injected stream and allows cancelling the bounded session", () => {
    vi.useFakeTimers();
    try {
      renderCancellableInjectedStream();
    } finally {
      vi.useRealTimers();
    }
  });

  function renderCancellableInjectedStream(): void {
    render(
      <AskPengePage
        authState="linked"
        modelAvailable
        transport={createImmediateTransport([
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

    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(screen.getByRole("status")).toHaveTextContent(/^$/);
    act(() => vi.advanceTimersByTime(120));
    expect(screen.getByRole("status")).toHaveTextContent("synthetic household balance");

    fireEvent.click(screen.getByRole("button", { name: /Open evidence sheet/i }));
    expect(screen.getByText("Synthetic Penge report lookup")).toBeInTheDocument();
    expect(screen.getByText(/Synthetic DKK 1\.42M and EUR 194k/i)).toBeInTheDocument();
    expect(screen.getByText("full")).toBeInTheDocument();
    expect(screen.getByText("fresh")).toBeInTheDocument();
    expect(screen.getByText("mixed")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close evidence sheet" }));
    act(() => vi.runOnlyPendingTimers());
    expect(screen.queryByRole("region", { name: "Answer evidence sheet" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    expect(screen.getByText(/Answer cancelled/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  }

  it("does not let a completed stop clean up a retried session", async () => {
    let resolveFirstStop: (() => void) | undefined;
    const firstUnsubscribe = vi.fn();
    const secondUnsubscribe = vi.fn();
    const firstClose = vi.fn();
    const secondClose = vi.fn();
    let starts = 0;
    const transport: AskTransport = {
      start() {
        starts += 1;
        const isFirst = starts === 1;
        return {
          stop: isFirst
            ? () =>
                new Promise<void>((resolve) => {
                  resolveFirstStop = resolve;
                })
            : async () => undefined,
          close: isFirst ? firstClose : secondClose,
          subscribe: () => (isFirst ? firstUnsubscribe : secondUnsubscribe),
        };
      },
    };
    render(<AskPengePage authState="linked" modelAvailable transport={transport} />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Ask" }));
    await user.click(screen.getByRole("button", { name: "Stop" }));
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(starts).toBe(2);

    await act(async () => {
      resolveFirstStop?.();
      await Promise.resolve();
    });

    expect(firstClose).toHaveBeenCalledOnce();
    expect(firstUnsubscribe).toHaveBeenCalledOnce();
    expect(secondClose).not.toHaveBeenCalled();
    expect(secondUnsubscribe).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument();
  });

  it("ignores a stale stop failure after a newer attempt starts", async () => {
    let rejectFirstStop: ((error: Error) => void) | undefined;
    let starts = 0;
    const transport: AskTransport = {
      start() {
        starts += 1;
        const isFirst = starts === 1;
        return {
          stop: isFirst
            ? () =>
                new Promise<void>((_resolve, reject) => {
                  rejectFirstStop = reject;
                })
            : async () => undefined,
          close: () => undefined,
          subscribe: () => () => undefined,
        };
      },
    };
    render(<AskPengePage authState="linked" modelAvailable transport={transport} />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Ask" }));
    await user.click(screen.getByRole("button", { name: "Stop" }));
    await user.click(screen.getByRole("button", { name: "Retry" }));
    await act(async () => {
      rejectFirstStop?.(new Error("synthetic stop failure"));
      await Promise.resolve();
    });
    expect(screen.queryByText(/could not confirm cancellation/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument();
  });

  it("reports an unconfirmed stop without mislabeling the stream and allows reconnecting", async () => {
    let starts = 0;
    const transport: AskTransport = {
      start() {
        starts += 1;
        return {
          stop: async () => {
            throw new Error("synthetic stop failure");
          },
          close: () => undefined,
          subscribe: () => () => undefined,
        };
      },
    };
    render(<AskPengePage authState="linked" modelAvailable transport={transport} />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Ask" }));
    await user.click(screen.getByRole("button", { name: "Stop" }));

    expect(await screen.findByText("Cancellation could not be confirmed")).toBeInTheDocument();
    expect(screen.getByText(/server could not confirm cancellation/i)).toBeInTheDocument();
    expect(screen.queryByText("Unsupported answer stream")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Reconnect" }));
    expect(starts).toBe(2);
    expect(screen.queryByText("Cancellation could not be confirmed")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument();
  });

  it.each([
    ["hydrafusion_unavailable", "Retry"],
    ["session_interrupted", "Reconnect"],
  ] as const)("reuses the submitted question after %s", async (code, recoveryAction) => {
    const requests: string[] = [];
    const transport: AskTransport = {
      start(request) {
        requests.push(request.question);
        const firstAttempt = requests.length === 1;
        return {
          stop: async () => undefined,
          close: () => undefined,
          subscribe: (callback) => {
            if (firstAttempt) {
              callback({
                ...envelope(0),
                type: "error",
                id: `error-${code}`,
                code,
                message: `Synthetic ${code} recovery.`,
                retryable: code === "session_interrupted",
              });
            }
            return () => undefined;
          },
        };
      },
    };
    render(<AskPengePage authState="linked" modelAvailable transport={transport} />);
    const user = userEvent.setup();
    const input = screen.getByRole("textbox", { name: "Ask Penge" });

    await user.clear(input);
    await user.type(input, "Synthetic submitted question");
    await user.click(screen.getByRole("button", { name: "Ask" }));
    await user.clear(input);
    await user.click(screen.getByRole("button", { name: recoveryAction }));

    expect(requests).toEqual(["Synthetic submitted question", "Synthetic submitted question"]);
  });

  it("blocks keyboard submissions while a session is streaming", async () => {
    useMediaQueryMock.mockReturnValue(false);
    let starts = 0;
    const transport: AskTransport = {
      start() {
        starts += 1;
        return {
          stop: async () => undefined,
          close: () => undefined,
          subscribe: () => () => undefined,
        };
      },
    };
    render(<AskPengePage authState="linked" modelAvailable transport={transport} />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Ask" }));
    const input = screen.getByRole("textbox", { name: "Ask Penge" });
    fireEvent.keyDown(input, { key: "Enter", ctrlKey: true });
    fireEvent.keyDown(input, { key: "Enter", metaKey: true });

    expect(starts).toBe(1);
    expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument();
    expect(screen.getByText("Answer streaming")).toBeInTheDocument();
  });

  it("latches protocol failure so later events cannot modify the answer", async () => {
    const transport: AskTransport = {
      start() {
        return {
          stop: async () => undefined,
          close: () => undefined,
          subscribe: (callback) => {
            callback({
              ...envelope(1),
              type: "text",
              id: "out-of-order",
              stream: "answer",
              delta: "Out of order.",
              source: "assistant",
            });
            callback({
              ...envelope(0),
              type: "text",
              id: "after-failure",
              stream: "answer",
              delta: "Must not render.",
              source: "assistant",
            });
            callback({
              ...envelope(1),
              type: "completion",
              id: "after-failure-completion",
              summary: "Synthetic completion after failure.",
              coverage: "full",
              freshness: "fresh",
              finishReason: "completed",
              assumptions: [],
            });
            return () => undefined;
          },
        };
      },
    };
    render(<AskPengePage authState="linked" modelAvailable transport={transport} />);

    await startInjectedStream();
    expect(await screen.findByText("Unsupported answer stream")).toBeInTheDocument();
    await new Promise((resolve) => setTimeout(resolve, 150));
    expect(screen.queryByText(/Must not render/)).not.toBeInTheDocument();
    expect(screen.queryByText("Synthetic completion after failure.")).not.toBeInTheDocument();
  });

  it.each([
    ["desktop", false],
    ["mobile", true],
  ] as const)(
    "does not present a rejected completion as successful on %s",
    async (_viewport, isMobile) => {
      useMediaQueryMock.mockReturnValue(isMobile);
      const transport: AskTransport = {
        start() {
          return {
            stop: async () => undefined,
            close: () => undefined,
            subscribe: (callback) => {
              callback({
                ...envelope(0),
                type: "text",
                id: "partial-before-completion",
                stream: "answer",
                delta: "Validated partial answer.",
                source: "assistant",
              });
              callback({
                ...envelope(1),
                type: "completion",
                id: "rejected-completion",
                summary: "Synthetic answer complete.",
                coverage: "full",
                freshness: "fresh",
                finishReason: "completed",
                assumptions: ["Synthetic completion assumption."],
              });
              callback({
                ...envelope(2),
                type: "text",
                id: "after-terminal",
                stream: "answer",
                delta: "Invalid extra text.",
                source: "assistant",
              });
              return () => undefined;
            },
          };
        },
      };
      render(<AskPengePage authState="linked" modelAvailable transport={transport} />);

      await startInjectedStream();
      expect(screen.getByText("Unsupported answer stream")).toBeInTheDocument();
      expect(screen.getByRole("status")).toHaveTextContent("Validated partial answer.");
      if (isMobile) {
        await userEvent.click(screen.getByRole("button", { name: /Open evidence sheet/i }));
      } else {
        expect(
          screen.queryByRole("button", { name: /Open evidence sheet/i }),
        ).not.toBeInTheDocument();
        expect(screen.getByText("Answer incomplete")).toBeInTheDocument();
      }
      expect(screen.queryByText("Synthetic answer complete.")).not.toBeInTheDocument();
      expect(screen.queryByText("Synthetic completion assumption.")).not.toBeInTheDocument();
      expect(screen.queryByText("Answer ready")).not.toBeInTheDocument();
      expect(screen.queryByText("Invalid extra text.")).not.toBeInTheDocument();
    },
  );

  it("requests an authoritative status refresh when authorization expires", async () => {
    const onAuthExpired = vi.fn();
    render(
      <AskPengePage
        authState="linked"
        modelAvailable
        onAuthExpired={onAuthExpired}
        transport={createImmediateTransport([
          {
            ...envelope(0),
            type: "error",
            id: "expired",
            code: "auth_expired",
            message: "Synthetic expired authorization.",
            retryable: false,
          },
        ])}
      />,
    );

    await startInjectedStream();
    expect(await screen.findByText("GitHub session expired")).toBeInTheDocument();
    expect(onAuthExpired).toHaveBeenCalledOnce();
  });

  it("exposes pressed evidence filters and preserves empty filtered results", async () => {
    useMediaQueryMock.mockReturnValue(false);
    render(
      <AskPengePage
        authState="linked"
        modelAvailable
        transport={createImmediateTransport([
          {
            ...envelope(0),
            type: "evidence",
            id: "fresh-full",
            title: "Fresh full source",
            source: "Synthetic Penge source",
            coverage: "full",
            freshness: "fresh",
            currency: "EUR",
            summary: "Synthetic fresh evidence.",
          },
          {
            ...envelope(1),
            type: "evidence",
            id: "stale-full",
            title: "Stale full source",
            source: "Synthetic Penge source",
            coverage: "full",
            freshness: "stale",
            currency: "DKK",
            summary: "Synthetic stale evidence.",
          },
          {
            ...envelope(2),
            type: "completion",
            id: "complete",
            summary: "Synthetic answer complete.",
            coverage: "full",
            freshness: "fresh",
            finishReason: "completed",
            assumptions: [],
          },
        ])}
      />,
    );
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Ask" }));
    const allFilter = screen.getByRole("button", { name: "All" });
    const attentionFilter = screen.getByRole("button", { name: "Needs attention" });
    expect(allFilter).toHaveAttribute("aria-pressed", "true");
    expect(attentionFilter).toHaveAttribute("aria-pressed", "false");

    await user.click(attentionFilter);
    expect(attentionFilter).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByText("Fresh full source")).not.toBeInTheDocument();
    expect(screen.getByText("Stale full source")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Fresh" }));
    expect(screen.getByText("Fresh full source")).toBeInTheDocument();
    expect(screen.queryByText("Stale full source")).not.toBeInTheDocument();
  });

  it("shows an empty result instead of falling back to all evidence", async () => {
    useMediaQueryMock.mockReturnValue(false);
    render(
      <AskPengePage
        authState="linked"
        modelAvailable
        transport={createImmediateTransport([
          {
            ...envelope(0),
            type: "evidence",
            id: "fresh-full",
            title: "Only fresh full source",
            source: "Synthetic Penge source",
            coverage: "full",
            freshness: "fresh",
            currency: "EUR",
            summary: "Synthetic fresh evidence.",
          },
        ])}
      />,
    );
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Ask" }));
    await user.click(screen.getByRole("button", { name: "Needs attention" }));

    expect(screen.getByText("No evidence records yet.")).toBeInTheDocument();
    expect(screen.queryByText("Only fresh full source")).not.toBeInTheDocument();
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
            message: "Synthetic model-unavailable detail.",
            retryable: false,
          },
        ])}
      />,
    );

    await startInjectedStream();
    await waitFor(() =>
      expect(screen.getByText("Exact Copilot Fusion model is unavailable")).toBeInTheDocument(),
    );
    expect(screen.getByText("Synthetic model-unavailable detail.")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/^$/);
  });

  it("labels EUR and DKK as supported currencies, not as evidence", async () => {
    useMediaQueryMock.mockReturnValue(false);
    render(
      <AskPengePage
        authState="linked"
        modelAvailable
        transport={createImmediateTransport([
          {
            ...envelope(0),
            type: "error",
            id: "missing-fx",
            code: "missing_fx",
            message: "Synthetic FX evidence is missing.",
            retryable: true,
          },
        ])}
      />,
    );

    expect(screen.getByText("EUR + DKK supported")).toBeInTheDocument();
    expect(screen.queryByText("EUR + DKK evidence")).not.toBeInTheDocument();
    await startInjectedStream();
    expect(await screen.findByText("EUR/DKK FX evidence is missing")).toBeInTheDocument();
    expect(screen.getByText("EUR + DKK supported")).toBeInTheDocument();
    expect(screen.queryByText("EUR + DKK evidence")).not.toBeInTheDocument();
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
          stop: async () => {
            stopped = true;
          },
          close: () => {
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
    useMediaQueryMock.mockReturnValue(false);
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
    expect(screen.getByText("Answer interrupted")).toBeInTheDocument();
    expect(screen.queryByText("Answer ready")).not.toBeInTheDocument();
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

  it("flushes buffered text and releases the timer on protocol errors", () => {
    vi.useFakeTimers();
    const setTimeoutSpy = vi.spyOn(globalThis, "setTimeout");
    const clearTimeoutSpy = vi.spyOn(globalThis, "clearTimeout");
    try {
      const transport: AskTransport = {
        start() {
          return {
            stop: async () => undefined,
            close: () => undefined,
            subscribe: (callback) => {
              callback({
                ...envelope(0),
                type: "text",
                id: "partial-before-error",
                stream: "answer",
                delta: "Validated partial.",
                source: "assistant",
              });
              callback({ type: "text", version: "2.0" });
              return () => undefined;
            },
          };
        },
      };
      render(<AskPengePage authState="linked" modelAvailable transport={transport} />);
      fireEvent.click(screen.getByRole("button", { name: "Ask" }));
      expect(screen.getByText("Unsupported answer stream")).toBeInTheDocument();
      expect(screen.getByRole("status")).toHaveTextContent("Validated partial.");
      const bufferTimerIndex = setTimeoutSpy.mock.calls.findIndex(([, delay]) => delay === 120);
      expect(bufferTimerIndex).toBeGreaterThanOrEqual(0);
      const bufferTimer = setTimeoutSpy.mock.results[bufferTimerIndex]?.value;
      expect(bufferTimer).toBeDefined();
      expect(clearTimeoutSpy).toHaveBeenCalledWith(bufferTimer);
    } finally {
      setTimeoutSpy.mockRestore();
      clearTimeoutSpy.mockRestore();
      vi.useRealTimers();
    }
  });

  it("presents cancelled completions with non-success severity", async () => {
    useMediaQueryMock.mockReturnValue(false);
    render(
      <AskPengePage
        authState="linked"
        modelAvailable
        transport={createImmediateTransport([
          {
            ...envelope(0),
            type: "completion",
            id: "cancelled-completion",
            summary: "Synthetic answer stopped early.",
            coverage: "partial",
            freshness: "fresh",
            finishReason: "cancelled",
            assumptions: [],
          },
        ])}
      />,
    );

    await startInjectedStream();
    const alert = (await screen.findByText("Synthetic answer stopped early.")).closest(
      ".MuiAlert-root",
    );
    expect(alert).toHaveClass("MuiAlert-colorWarning");
    expect(alert).not.toHaveClass("MuiAlert-colorSuccess");
    expect(screen.getByText("Answer stopped")).toBeInTheDocument();
    expect(screen.queryByText("Answer ready")).not.toBeInTheDocument();
  });

  it.each([
    ["partial", "fresh", "MuiAlert-colorWarning", "Answer needs review"],
    ["full", "stale", "MuiAlert-colorWarning", "Answer needs review"],
    ["full", "fresh", "MuiAlert-colorSuccess", "Answer ready"],
  ] as const)(
    "styles a %s/%s completed answer according to its evidence quality",
    async (coverage, freshness, severityClass, statusLabel) => {
      useMediaQueryMock.mockReturnValue(false);
      render(
        <AskPengePage
          authState="linked"
          modelAvailable
          transport={createImmediateTransport([
            {
              ...envelope(0),
              type: "completion",
              id: `completed-${coverage}-${freshness}`,
              summary: "Synthetic completed answer.",
              coverage,
              freshness,
              finishReason: "completed",
              assumptions: [],
            },
          ])}
        />,
      );

      await startInjectedStream();
      const alert = (await screen.findByText("Synthetic completed answer.")).closest(
        ".MuiAlert-root",
      );
      expect(alert).toHaveClass(severityClass);
      expect(screen.getByText(statusLabel)).toBeInTheDocument();
    },
  );

  it("buffers answer announcements and flushes them when cancelled", async () => {
    vi.useFakeTimers();
    const setTimeoutSpy = vi.spyOn(globalThis, "setTimeout");
    const clearTimeoutSpy = vi.spyOn(globalThis, "clearTimeout");
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
      const bufferTimerIndex = setTimeoutSpy.mock.calls.findIndex(([, delay]) => delay === 120);
      expect(bufferTimerIndex).toBeGreaterThanOrEqual(0);
      const bufferTimer = setTimeoutSpy.mock.results[bufferTimerIndex]?.value;
      expect(bufferTimer).toBeDefined();
      expect(screen.getByRole("status")).toHaveTextContent(/^$/);
      act(() => vi.advanceTimersByTime(119));
      expect(screen.getByRole("status")).toHaveTextContent(/^$/);

      fireEvent.click(screen.getByRole("button", { name: "Stop" }));
      expect(screen.getByRole("status")).toHaveTextContent("Buffered answer.");
      expect(clearTimeoutSpy).toHaveBeenCalledWith(bufferTimer);
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
      setTimeoutSpy.mockClear();
      clearTimeoutSpy.mockClear();
      fireEvent.click(screen.getByRole("button", { name: "Ask" }));
      const pendingTimerIndex = setTimeoutSpy.mock.calls.findIndex(([, delay]) => delay === 120);
      expect(pendingTimerIndex).toBeGreaterThanOrEqual(0);
      const pendingTimer = setTimeoutSpy.mock.results[pendingTimerIndex]?.value;
      expect(pendingTimer).toBeDefined();
      pending.unmount();
      expect(clearTimeoutSpy).toHaveBeenCalledWith(pendingTimer);
    } finally {
      setTimeoutSpy.mockRestore();
      clearTimeoutSpy.mockRestore();
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
    useMediaQueryMock.mockReturnValue(false);
    const start = vi.fn((_request: AskRequest) =>
      createTransport([]).start({ question: "unused" }),
    );
    const transport: AskTransport = { start };

    render(<AskPengePage transport={transport} />);

    expect(start).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "GitHub linking unavailable" })).toBeDisabled();
    expect(screen.getByText("EUR + DKK supported")).toBeInTheDocument();
    expect(screen.queryByText("EUR + DKK evidence")).not.toBeInTheDocument();
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
