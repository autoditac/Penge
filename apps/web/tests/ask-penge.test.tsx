/** Component tests for the Ask Penge workbench.
 * @vitest-environment jsdom
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { AskPengePage } from "../src/ask-penge/AskPengePage";
import { askStreamEventSchema } from "../src/ask-penge/contract";
import type { AskStreamEvent, AskTransport } from "../src/ask-penge/contract";

function createTransport(events: ReadonlyArray<AskStreamEvent>): AskTransport {
  return {
    start() {
      let index = 0;
      const listeners = new Set<(event: AskStreamEvent) => void>();

      const emitNext = () => {
        if (index >= events.length) {
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
          setTimeout(emitNext, 25);
        }
      };

      const session = {
        stop: () => {
          index = events.length;
        },
        retry: () => {
          index = 0;
          emitNext();
        },
        subscribe: (callback: (event: AskStreamEvent) => void) => {
          listeners.add(callback);
          emitNext();
          return () => {
            listeners.delete(callback);
          };
        },
      };

      return session;
    },
  };
}

describe("AskPengePage", () => {
  it("renders the streamed evidence workbench and allows stopping the session", async () => {
    render(
      <AskPengePage
        transport={createTransport([
          {
            type: "tool",
            id: "tool-1",
            name: "HydraFusion exact review",
            status: "started",
            detail: "Confirming the exact data path and freshness window.",
            startedAt: new Date().toISOString(),
          },
          {
            type: "text",
            id: "text-1",
            stream: "answer",
            delta: "The household balance looks stable.",
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
        ])}
      />,
    );

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Ask Penge" })).toBeInTheDocument(),
    );
    expect(screen.getByText("GitHub account required")).toBeInTheDocument();
    expect(screen.getByText("HydraFusion exact review")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getAllByText(/DKK 1\.42M and EUR 194k/i).length).toBeGreaterThan(0),
    );

    const user = userEvent.setup();
    await waitFor(() => expect(screen.getByRole("button", { name: /^Stop$/ })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /^Stop$/ }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /^Retry$/ })).toBeInTheDocument(),
    );
  });

  it("surfaces hydration/auth failures without inventing a complete answer", async () => {
    render(
      <AskPengePage
        transport={createTransport([
          {
            type: "error",
            id: "error-1",
            code: "hydrafusion_unavailable",
            message: "Exact HydraFusion data is unavailable for this household.",
            retryable: false,
          },
        ])}
      />,
    );

    await waitFor(() =>
      expect(screen.getByText("Exact HydraFusion data is unavailable")).toBeInTheDocument(),
    );
    expect(
      screen.getByText("Exact HydraFusion data is unavailable for this household."),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { name: "Ask Penge" }).length).toBeGreaterThan(0);
  });

  it("rejects malformed events before they reach the render layer", () => {
    expect(() =>
      askStreamEventSchema.parse({
        type: "text",
        id: "bad",
        stream: "answer",
        delta: 42,
        source: "assistant",
      }),
    ).toThrow();
  });
});
