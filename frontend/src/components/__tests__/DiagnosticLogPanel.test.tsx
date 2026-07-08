import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DiagnosticLogPanel } from "../DiagnosticLogPanel";

describe("DiagnosticLogPanel", () => {
  it("shows empty state", () => {
    render(<DiagnosticLogPanel lines={[]} emptyLabel="No logs" />);
    expect(screen.getByText("No logs")).toBeInTheDocument();
  });

  it("renders log lines", () => {
    render(
      <DiagnosticLogPanel
        lines={[
          {
            ts: "2026-07-03T12:00:00Z",
            level: "error",
            step: "proxy",
            message: "Connection refused",
          },
        ]}
      />
    );
    expect(screen.getByText("proxy")).toBeInTheDocument();
    expect(screen.getByText("Connection refused")).toBeInTheDocument();
  });
});
