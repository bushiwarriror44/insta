import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EmptyState } from "../EmptyState";

describe("EmptyState", () => {
  it("renders optional title and action", () => {
    render(
      <EmptyState
        title="Нет данных"
        action={
          <button type="button">Дальше</button>
        }
      >
        Описание пустого состояния.
      </EmptyState>
    );
    expect(screen.getByText("Нет данных")).toBeInTheDocument();
    expect(screen.getByText("Описание пустого состояния.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Дальше" })).toBeInTheDocument();
  });
});
