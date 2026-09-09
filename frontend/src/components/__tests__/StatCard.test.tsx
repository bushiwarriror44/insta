import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Activity, Users } from "lucide-react";
import { describe, expect, it } from "vitest";

import { StatCard } from "../StatCard";

describe("StatCard", () => {
  it("renders label and value", () => {
    render(<StatCard label="Active" value={42} icon={Users} />);
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
  });

  it("renders an optional hint", () => {
    render(<StatCard label="x" value="y" icon={Users} hint="some hint" />);
    expect(screen.getByText("some hint")).toBeInTheDocument();
  });

  it("supports string values", () => {
    render(<StatCard label="ratio" value="3 / 10" icon={Activity} />);
    expect(screen.getByText("3 / 10")).toBeInTheDocument();
  });

  it("wraps the card in a link when to is set", () => {
    render(
      <MemoryRouter>
        <StatCard label="Active" value={1} icon={Users} to="/accounts" />
      </MemoryRouter>
    );
    expect(screen.getByRole("link", { name: "Active" })).toHaveAttribute("href", "/accounts");
  });

  it("applies tone-based styles", () => {
    const { container, rerender } = render(
      <StatCard label="x" value="y" icon={Users} tone="success" />
    );
    expect(container.querySelector(".bg-emerald-900\\/40")).not.toBeNull();

    rerender(<StatCard label="x" value="y" icon={Users} tone="danger" />);
    expect(container.querySelector(".bg-rose-900\\/40")).not.toBeNull();
  });
});
