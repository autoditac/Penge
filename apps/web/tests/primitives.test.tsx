/** Component tests for shared primitives (issue #271 design system).
 * @vitest-environment jsdom
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  EmptyState,
  ErrorState,
  LoadingState,
  MetricCard,
  Panel,
  PageHeader,
  Pill,
  SegmentedControl,
  TableScroll,
} from "../src/components/primitives";
import { renderWithTheme } from "./test-utils";

describe("PageHeader", () => {
  it("renders title, description, and optional badge", () => {
    renderWithTheme(
      <PageHeader title="Performance" description="Net-worth trends" badge={<span>demo</span>} />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Performance" })).toBeInTheDocument();
    expect(screen.getByText("Net-worth trends")).toBeInTheDocument();
    expect(screen.getByText("demo")).toBeInTheDocument();
  });

  it("omits the description block when none is given", () => {
    renderWithTheme(<PageHeader title="Imports" />);
    expect(screen.getByRole("heading", { name: "Imports" })).toBeInTheDocument();
  });
});

describe("Panel", () => {
  it("renders eyebrow, title, actions, and children", () => {
    renderWithTheme(
      <Panel eyebrow="Step 1" title="Upload" actions={<span>action-slot</span>}>
        <p>panel body</p>
      </Panel>,
    );
    expect(screen.getByText("Step 1")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Upload" })).toBeInTheDocument();
    expect(screen.getByText("action-slot")).toBeInTheDocument();
    expect(screen.getByText("panel body")).toBeInTheDocument();
  });
});

describe("MetricCard", () => {
  it("renders label, value, and optional detail", () => {
    renderWithTheme(
      <MetricCard label="Net worth" detail="vs. last month" tone="good">
        123.45 EUR
      </MetricCard>,
    );
    expect(screen.getByText("Net worth")).toBeInTheDocument();
    expect(screen.getByText("123.45 EUR")).toBeInTheDocument();
    expect(screen.getByText("vs. last month")).toBeInTheDocument();
  });
});

describe("Pill", () => {
  it("renders its label text for every tone", () => {
    renderWithTheme(<Pill tone="critical">error</Pill>);
    expect(screen.getByText("error")).toBeInTheDocument();
  });
});

describe("SegmentedControl", () => {
  it("renders each option and reports the selected value on change", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderWithTheme(
      <SegmentedControl
        options={[
          { value: "1M", label: "1M" },
          { value: "1Y", label: "1Y" },
        ]}
        value="1M"
        onChange={onChange}
        ariaLabel="History range"
      />,
    );
    const group = screen.getByRole("group", { name: "History range" });
    expect(group).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "1Y" }));
    expect(onChange).toHaveBeenCalledWith("1Y");
  });

  it("does not report a change when re-clicking the already-selected option", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderWithTheme(
      <SegmentedControl
        options={[
          { value: "1M", label: "1M" },
          { value: "1Y", label: "1Y" },
        ]}
        value="1M"
        onChange={onChange}
        ariaLabel="History range"
      />,
    );
    await user.click(screen.getByRole("button", { name: "1M" }));
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe("LoadingState", () => {
  it("announces a polite loading status", () => {
    renderWithTheme(<LoadingState label="key figures" />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading key figures…");
  });
});

describe("ErrorState", () => {
  it("shows the error message and an optional retry action", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    renderWithTheme(
      <ErrorState label="accounts" error={new Error("network down")} onRetry={onRetry} />,
    );
    expect(screen.getByText("network down")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("omits the retry action when none is provided", () => {
    renderWithTheme(<ErrorState label="accounts" error={new Error("boom")} />);
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
  });
});

describe("EmptyState", () => {
  it("renders a note about the missing data", () => {
    renderWithTheme(<EmptyState label="fees" />);
    expect(screen.getByRole("note")).toHaveTextContent(/no fees available/i);
  });
});

describe("TableScroll", () => {
  it("wraps its table child in a scrollable region", () => {
    renderWithTheme(
      <TableScroll>
        <table>
          <tbody>
            <tr>
              <td>cell</td>
            </tr>
          </tbody>
        </table>
      </TableScroll>,
    );
    expect(screen.getByText("cell")).toBeInTheDocument();
  });
});
