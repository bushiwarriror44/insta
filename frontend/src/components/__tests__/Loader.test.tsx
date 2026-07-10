import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Loader } from "../Loader";

describe("Loader", () => {
  it("renders the default label", () => {
    render(<Loader />);
    expect(screen.getByText("Загрузка...")).toBeInTheDocument();
  });

  it("renders a custom label", () => {
    render(<Loader label="Connecting..." />);
    expect(screen.getByText("Connecting...")).toBeInTheDocument();
  });
});
