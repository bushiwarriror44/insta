import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Card } from "../Card";

describe("Card", () => {
  it("renders children and title", () => {
    render(
      <Card title="Header">
        <span>body content</span>
      </Card>
    );
    expect(screen.getByRole("heading", { name: "Header" })).toBeInTheDocument();
    expect(screen.getByText("body content")).toBeInTheDocument();
  });

  it("renders description and actions when provided", () => {
    render(
      <Card title="t" description="some description" actions={<button>act</button>}>
        body
      </Card>
    );
    expect(screen.getByText("some description")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "act" })).toBeInTheDocument();
  });

  it("omits the header when no title and no actions", () => {
    const { container } = render(<Card>plain</Card>);
    expect(container.querySelector("header")).toBeNull();
    expect(screen.getByText("plain")).toBeInTheDocument();
  });

  it("spaces body children and keeps grid class on the section", () => {
    const { container } = render(
      <Card className="xl:col-span-2">
        <span>first</span>
        <span>second</span>
      </Card>
    );
    const section = container.querySelector("section");
    expect(section?.className).toMatch(/xl:col-span-2/);
    expect(section?.className).not.toMatch(/\bp-4\b/);
    const body = section?.firstElementChild as HTMLElement;
    expect(body.className).toMatch(/gap-4/);
    expect(body.className).toMatch(/p-5/);
    expect(body.children).toHaveLength(2);
  });

  it("renders header when only actions provided", () => {
    const { container } = render(
      <Card actions={<span>x</span>}>body</Card>
    );
    expect(container.querySelector("header")).not.toBeNull();
  });
});
