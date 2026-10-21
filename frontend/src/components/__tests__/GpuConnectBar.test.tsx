import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { GpuOut } from "../../api/types";
import { GpuConnectBar } from "../GpuConnectBar";

function gpu(overrides: Partial<GpuOut> = {}): GpuOut {
  return {
    configured: true,
    status: "deploying",
    billing: false,
    allocating_count: 0,
    creating_count: 1,
    running_count: 0,
    stopping_count: 0,
    chat_ok: false,
    wan_ok: null,
    detail: "",
    connect_phase: "pull",
    connect_label: "Качается образ на узел",
    connect_detail: "12 с · работают 0, создаются 1, выделяются 0",
    connect_ratio: 0.45,
    ...overrides,
  };
}

describe("GpuConnectBar", () => {
  it("hides when the phase is idle", () => {
    const { container } = render(<GpuConnectBar gpu={gpu({ connect_phase: "idle", connect_ratio: 0 })} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows a partial bar for pull", () => {
    render(<GpuConnectBar gpu={gpu()} />);
    expect(screen.getByText("Качается образ на узел")).toBeInTheDocument();
    const bar = screen.getByRole("progressbar", { name: /качается образ/i });
    expect(bar).toHaveAttribute("aria-valuenow", "45");
  });

  it("hides ready unless includeReady is set", () => {
    const ready = gpu({
      status: "running",
      connect_phase: "ready",
      connect_label: "Чат отвечает",
      connect_ratio: 1,
      chat_ok: true,
    });
    const { rerender, container } = render(<GpuConnectBar gpu={ready} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<GpuConnectBar gpu={ready} includeReady />);
    expect(screen.getByText("Чат отвечает")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
  });
});
