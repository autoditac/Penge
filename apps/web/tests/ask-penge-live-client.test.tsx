/** Tests for the production Ask Penge fetch/SSE adapter.
 * @vitest-environment jsdom
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AskPengeLivePage } from "../src/ask-penge/AskPengeLivePage";
import {
  AskChatClientError,
  SseDataParser,
  createAskChatClient,
  resolveSameOriginBaseUrl,
} from "../src/ask-penge/liveClient";
import type { FetchLike } from "../src/ask-penge/liveClient";

const currentLocation = "https://penge.example/app/ask";
const baseUrl = "/chat/";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function streamResponse(chunks: readonly string[], status = 200): Response {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        for (const chunk of chunks) {
          controller.enqueue(encoder.encode(chunk));
        }
        controller.close();
      },
    }),
    {
      status,
      headers: { "Content-Type": "text/event-stream" },
    },
  );
}

function statusResponse(
  overrides: {
    state?: "linked" | "not-linked" | "expired";
    login?: string | null;
    available?: boolean;
    featureEnabled?: boolean;
  } = {},
): Response {
  return jsonResponse({
    github: {
      state: overrides.state ?? "linked",
      login: overrides.login === undefined ? "synthetic-user" : overrides.login,
    },
    model: {
      id: "hydrafusion",
      available: overrides.available ?? true,
    },
    featureEnabled: overrides.featureEnabled ?? true,
  });
}

function asFetch(mock: ReturnType<typeof vi.fn>): FetchLike {
  return mock as unknown as FetchLike;
}

describe("Ask Penge live client", () => {
  it("normalizes same-origin base URLs and rejects cross-origin configuration", () => {
    expect(
      resolveSameOriginBaseUrl("/chat?ignored=true#fragment", currentLocation).toString(),
    ).toBe("https://penge.example/chat/");
    expect(resolveSameOriginBaseUrl("/ask/api/", currentLocation).toString()).toBe(
      "https://penge.example/ask/api/",
    );
    expect(() =>
      resolveSameOriginBaseUrl("https://attacker.example/chat", currentLocation),
    ).toThrowError(AskChatClientError);
  });

  it("loads strict status, exposes the OAuth URL, and unlinks with same-origin credentials", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(statusResponse())
      .mockResolvedValueOnce(jsonResponse({ status: "unlinked" }));
    const client = createAskChatClient(baseUrl, asFetch(fetchMock), currentLocation);

    await expect(client.getStatus()).resolves.toMatchObject({
      github: { state: "linked", login: "synthetic-user" },
      model: { id: "hydrafusion", available: true },
      featureEnabled: true,
    });
    expect(client.githubStartUrl).toBe("https://penge.example/chat/oauth/github/start");
    await client.unlinkGitHub();

    expect(String(fetchMock.mock.calls[0]?.[0])).toBe("https://penge.example/chat/v1/auth/status");
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({ credentials: "same-origin" });
    expect(String(fetchMock.mock.calls[1]?.[0])).toBe("https://penge.example/chat/v1/auth/github");
    expect(fetchMock.mock.calls[1]?.[1]).toMatchObject({
      method: "DELETE",
      credentials: "same-origin",
    });
  });

  it("rejects malformed or expanded status responses", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        github: { state: "linked", login: "synthetic-user" },
        model: { id: "fallback-model", available: true },
        featureEnabled: true,
        clientEntitlement: true,
      }),
    );
    const client = createAskChatClient(baseUrl, asFetch(fetchMock), currentLocation);

    await expect(client.getStatus()).rejects.toThrow();
  });

  it.each([
    [{ state: "linked", login: null }, "linked without a login"],
    [{ state: "not-linked", login: "synthetic-user" }, "unlinked with a login"],
  ])("rejects semantically inconsistent GitHub status: %s", async (github, _description) => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        github,
        model: { id: "hydrafusion", available: true },
        featureEnabled: true,
      }),
    );
    const client = createAskChatClient(baseUrl, asFetch(fetchMock), currentLocation);

    await expect(client.getStatus()).rejects.toThrow();
  });

  it("accepts expired status with or without the last known login", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(statusResponse({ state: "expired", login: null }))
      .mockResolvedValueOnce(statusResponse({ state: "expired", login: "synthetic-user" }));
    const client = createAskChatClient(baseUrl, asFetch(fetchMock), currentLocation);

    await expect(client.getStatus()).resolves.toMatchObject({
      github: { state: "expired", login: null },
    });
    await expect(client.getStatus()).resolves.toMatchObject({
      github: { state: "expired", login: "synthetic-user" },
    });
  });

  it("parses split CRLF, multiline data, comments, and final unterminated events", () => {
    const parser = new SseDataParser();

    expect(parser.push(': keepalive\r\ndata: {"one":\r')).toEqual([]);
    expect(parser.push("\ndata: true}\r\n\r")).toEqual([]);
    expect(parser.push("\ndata: trailing")).toEqual(['{"one":\ntrue}']);
    expect(parser.finish()).toEqual(["trailing"]);
  });

  it("streams chunk-split events and sends no client member identity", async () => {
    const completion = JSON.stringify({
      version: "1.0",
      sessionId: "live-session",
      id: "completion-0",
      sequence: 0,
      type: "completion",
      summary: "Synthetic completion",
      coverage: "full",
      freshness: "fresh",
      finishReason: "completed",
      assumptions: [],
    });
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        streamResponse([`da`, `ta: ${completion.slice(0, 44)}`, `${completion.slice(44)}\n\n`]),
      );
    const client = createAskChatClient(baseUrl, asFetch(fetchMock), currentLocation);
    const session = client.transport.start({ question: "Synthetic question" });
    const received: unknown[] = [];

    await new Promise<void>((resolve) => {
      session.subscribe((event) => {
        received.push(event);
        resolve();
      });
    });

    expect(received).toHaveLength(1);
    expect(received[0]).toMatchObject({ type: "completion", sessionId: "live-session" });
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({
      method: "POST",
      credentials: "same-origin",
      body: JSON.stringify({ question: "Synthetic question" }),
    });
    expect(String(fetchMock.mock.calls[0]?.[1]?.body)).not.toContain("member");
  });

  it("rejects questions over 8,000 characters before fetching", () => {
    const fetchMock = vi.fn();
    const client = createAskChatClient(baseUrl, asFetch(fetchMock), currentLocation);

    expect(() => client.transport.start({ question: "x".repeat(8_001) })).toThrow();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([
    [401, "auth_expired", false],
    [403, "auth_expired", false],
    [429, "rate_limit", true],
    [504, "tool_timeout", true],
    [404, "session_interrupted", true],
    [503, "session_interrupted", true],
    [500, "session_interrupted", true],
  ] as const)("maps chat HTTP %i to %s", async (status, code, retryable) => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status }));
    const client = createAskChatClient(baseUrl, asFetch(fetchMock), currentLocation);
    const session = client.transport.start({ question: "Synthetic question" });

    const event = await new Promise<unknown>((resolve) => session.subscribe(resolve));

    expect(event).toMatchObject({ type: "error", code, retryable });
  });

  it("maps only an explicit bounded backend code to exact-model unavailability", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        jsonResponse({ code: "hydrafusion_unavailable", message: "Synthetic server detail" }, 503),
      );
    const client = createAskChatClient(baseUrl, asFetch(fetchMock), currentLocation);
    const session = client.transport.start({ question: "Synthetic question" });

    await expect(
      new Promise<unknown>((resolve) => session.subscribe(resolve)),
    ).resolves.toMatchObject({
      type: "error",
      code: "hydrafusion_unavailable",
      retryable: false,
    });
  });

  it("does not trust an oversized backend error body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(
        {
          code: "hydrafusion_unavailable",
          message: "x".repeat(4_097),
        },
        503,
      ),
    );
    const client = createAskChatClient(baseUrl, asFetch(fetchMock), currentLocation);
    const session = client.transport.start({ question: "Synthetic question" });

    await expect(
      new Promise<unknown>((resolve) => session.subscribe(resolve)),
    ).resolves.toMatchObject({
      type: "error",
      code: "session_interrupted",
    });
  });

  it("reports disconnects before a terminal event but not local aborts", async () => {
    const fetchMock = vi.fn().mockResolvedValue(streamResponse([]));
    const client = createAskChatClient(baseUrl, asFetch(fetchMock), currentLocation);
    const disconnectedSession = client.transport.start({ question: "Synthetic question" });

    await expect(
      new Promise<unknown>((resolve) => disconnectedSession.subscribe(resolve)),
    ).resolves.toMatchObject({ type: "error", code: "session_interrupted" });

    let resolveFetch: ((response: Response) => void) | undefined;
    const pendingFetch = vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          resolveFetch = resolve;
        }),
    );
    const abortingClient = createAskChatClient(baseUrl, asFetch(pendingFetch), currentLocation);
    const abortedSession = abortingClient.transport.start({ question: "Synthetic question" });
    const listener = vi.fn();
    abortedSession.subscribe(listener);
    abortedSession.close();
    resolveFetch?.(streamResponse([]));
    await Promise.resolve();
    await Promise.resolve();
    expect(listener).not.toHaveBeenCalled();
  });

  it("posts stop only after observing the server session and surfaces stop failure", async () => {
    const text = JSON.stringify({
      version: "1.0",
      sessionId: "server-session",
      id: "text-0",
      sequence: 0,
      type: "text",
      stream: "answer",
      delta: "Synthetic",
      source: "assistant",
    });
    let streamController: ReadableStreamDefaultController<Uint8Array> | undefined;
    const encoder = new TextEncoder();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          new ReadableStream<Uint8Array>({
            start(controller) {
              streamController = controller;
              controller.enqueue(encoder.encode(`data: ${text}\n\n`));
            },
          }),
        ),
      )
      .mockResolvedValueOnce(new Response(null, { status: 500 }));
    const client = createAskChatClient(baseUrl, asFetch(fetchMock), currentLocation);
    const session = client.transport.start({ question: "Synthetic question" });
    await new Promise<void>((resolve) => {
      session.subscribe(() => resolve());
    });

    await expect(session.stop()).rejects.toMatchObject({
      code: "chat_stop_failed",
      status: 500,
    });
    expect(fetchMock.mock.calls[1]?.[1]).toMatchObject({
      method: "POST",
      body: JSON.stringify({ sessionId: "server-session" }),
    });
    session.close();
    streamController?.close();
  });

  it("uses the response session header to stop before the first event", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(new ReadableStream<Uint8Array>({}), {
          headers: { "X-Penge-Chat-Session-Id": "header-session" },
        }),
      )
      .mockResolvedValueOnce(jsonResponse({ status: "cancelling" }, 202));
    const client = createAskChatClient(baseUrl, asFetch(fetchMock), currentLocation);
    const session = client.transport.start({ question: "Synthetic question" });
    session.subscribe(() => undefined);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    await Promise.resolve();

    await session.stop();

    expect(fetchMock.mock.calls[1]?.[1]).toMatchObject({
      method: "POST",
      body: JSON.stringify({ sessionId: "header-session" }),
    });
  });

  it("rejects a stream session that differs from the response session header", async () => {
    const completion = JSON.stringify({
      version: "1.0",
      sessionId: "event-session",
      id: "completion-0",
      sequence: 0,
      type: "completion",
      summary: "Synthetic completion",
      coverage: "full",
      freshness: "fresh",
      finishReason: "completed",
      assumptions: [],
    });
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        new ReadableStream<Uint8Array>({
          start(controller) {
            controller.enqueue(new TextEncoder().encode(`data: ${completion}\n\n`));
            controller.close();
          },
        }),
        { headers: { "X-Penge-Chat-Session-Id": "header-session" } },
      ),
    );
    const client = createAskChatClient(baseUrl, asFetch(fetchMock), currentLocation);
    const session = client.transport.start({ question: "Synthetic question" });
    const received: unknown[] = [];

    await new Promise<void>((resolve) => {
      session.subscribe((event) => {
        received.push(event);
        resolve();
      });
    });

    expect(received).toEqual([
      {
        sessionIdMismatch: { expected: "header-session", received: "event-session" },
      },
    ]);
  });

  it("passes malformed SSE data to the strict UI boundary", async () => {
    const fetchMock = vi.fn().mockResolvedValue(streamResponse(["data: {not-json}\n\n"]));
    const client = createAskChatClient(baseUrl, asFetch(fetchMock), currentLocation);
    const session = client.transport.start({ question: "Synthetic question" });

    await expect(new Promise<unknown>((resolve) => session.subscribe(resolve))).resolves.toEqual({
      malformedSseData: "{not-json}",
    });
  });
});

describe("Ask Penge live page", () => {
  it("stays fail closed without configuration and performs no fetch", () => {
    const fetchMock = vi.fn();

    render(<AskPengeLivePage configuredBaseUrl="" fetchFn={asFetch(fetchMock)} />);

    expect(screen.getByText("Exact HydraFusion is unavailable")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("renders loading then server-derived linked status and OAuth navigation", async () => {
    let resolveStatus: ((response: Response) => void) | undefined;
    const fetchMock = vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          resolveStatus = resolve;
        }),
    );
    const navigate = vi.fn();
    render(
      <AskPengeLivePage
        configuredBaseUrl="/chat"
        fetchFn={asFetch(fetchMock)}
        navigate={navigate}
      />,
    );

    expect(screen.getByText("Checking Ask Penge status")).toBeInTheDocument();
    resolveStatus?.(statusResponse({ state: "not-linked", login: null }));
    expect(await screen.findByText(/connect your own account/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Link GitHub account" }));
    expect(navigate).toHaveBeenCalledWith("http://localhost:3000/chat/oauth/github/start");
  });

  it("shows strict model, feature, and retry states from status", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(statusResponse({ available: false }))
      .mockResolvedValueOnce(statusResponse({ featureEnabled: false }))
      .mockRejectedValueOnce(new TypeError("synthetic disconnect"))
      .mockResolvedValueOnce(statusResponse({ state: "expired", login: null }));
    const { rerender } = render(
      <AskPengeLivePage configuredBaseUrl="/chat" fetchFn={asFetch(fetchMock)} />,
    );

    expect(await screen.findByText("Exact HydraFusion is unavailable")).toBeInTheDocument();
    rerender(
      <AskPengeLivePage
        key="feature-disabled"
        configuredBaseUrl="/chat"
        fetchFn={asFetch(fetchMock)}
      />,
    );
    expect(await screen.findByText("Ask Penge is disabled by the service")).toBeInTheDocument();
    rerender(
      <AskPengeLivePage
        key="status-error"
        configuredBaseUrl="/chat"
        fetchFn={asFetch(fetchMock)}
      />,
    );
    expect(await screen.findByText("Ask Penge status is unavailable")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry status" }));
    expect(await screen.findByText(/authorization expired/i)).toBeInTheDocument();
  });

  it("unlinks a linked account and refreshes status", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(statusResponse({ login: "synthetic-user" }))
      .mockResolvedValueOnce(jsonResponse({ status: "unlinked" }))
      .mockResolvedValueOnce(statusResponse({ state: "not-linked", login: null }));
    render(<AskPengeLivePage configuredBaseUrl="/chat" fetchFn={asFetch(fetchMock)} />);

    expect(await screen.findByText(/linked as @synthetic-user/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Unlink GitHub account" }));
    await waitFor(() => expect(screen.getByText(/connect your own account/i)).toBeInTheDocument());
    expect(String(fetchMock.mock.calls[1]?.[0])).toBe("http://localhost:3000/chat/v1/auth/github");
    expect(fetchMock.mock.calls[1]?.[1]).toMatchObject({ method: "DELETE" });
  });

  it("rejects a post-terminal live event at the protocol boundary", async () => {
    const completion = JSON.stringify({
      version: "1.0",
      sessionId: "live-session",
      id: "completion-0",
      sequence: 0,
      type: "completion",
      summary: "Synthetic completion",
      coverage: "full",
      freshness: "fresh",
      finishReason: "completed",
      assumptions: [],
    });
    const postTerminal = JSON.stringify({
      version: "1.0",
      sessionId: "live-session",
      id: "text-1",
      sequence: 1,
      type: "text",
      stream: "answer",
      delta: "Must not render",
      source: "assistant",
    });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(statusResponse())
      .mockResolvedValueOnce(streamResponse([`data: ${completion}\n\ndata: ${postTerminal}\n\n`]));
    render(<AskPengeLivePage configuredBaseUrl="/chat" fetchFn={asFetch(fetchMock)} />);

    await screen.findByText(/linked as @synthetic-user/i);
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByText("Unsupported answer stream")).toBeInTheDocument();
    expect(screen.queryByText("Must not render")).not.toBeInTheDocument();
  });
});
