import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatusBadge } from "../StatusBadge";

describe("StatusBadge", () => {
  it("renders the value text", () => {
    render(<StatusBadge value="queued" />);
    expect(screen.getByText("В очереди")).toBeInTheDocument();
  });

  it("applies the appropriate class for known statuses", () => {
    const { rerender } = render(<StatusBadge value="active" />);
    expect(screen.getByText("Активен").className).toMatch(/emerald/);

    rerender(<StatusBadge value="dead" />);
    expect(screen.getByText("Мёртвая").className).toMatch(/rose/);

    rerender(<StatusBadge value="running" />);
    expect(screen.getByText("В работе").className).toMatch(/sky/);

    rerender(<StatusBadge value="cooldown" />);
    expect(screen.getByText("Пауза IG").className).toMatch(/orange/);
  });

  it("uses neutral fallback for unknown values", () => {
    render(<StatusBadge value="totally-unknown" />);
    const badge = screen.getByText("totally-unknown");
    expect(badge.className).toMatch(/slate/);
  });

  it("normalizes case-insensitively", () => {
    render(<StatusBadge value="ACTIVE" />);
    const badge = screen.getByText("Активен");
    expect(badge.className).toMatch(/emerald/);
  });

  it("renders an icon next to the status label", () => {
    const { container } = render(<StatusBadge value="queued" />);
    expect(screen.getByText("В очереди")).toBeInTheDocument();
    expect(container.querySelector("svg")).toBeTruthy();
  });
});
