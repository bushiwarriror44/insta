import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../../api/client";
import { ConnectionMenu } from "../ConnectionMenu";

vi.mock("../../api/client", () => ({
  api: {
    gpu: {
      status: vi.fn(),
      start: vi.fn(),
      stop: vi.fn(),
    },
  },
  formatApiError: (err: unknown) => String(err),
}));

vi.mock("../../context/ToastContext", () => ({
  useToast: () => ({ push: vi.fn() }),
}));

function running() {
  return {
    configured: true,
    status: "running",
    billing: true,
    allocating_count: 0,
    creating_count: 0,
    running_count: 1,
    stopping_count: 0,
    chat_ok: true,
    wan_ok: null,
    detail: "",
  };
}

beforeEach(() => {
  vi.mocked(api.gpu.status).mockResolvedValue(running() as never);
  vi.mocked(api.gpu.stop).mockReset();
});

describe("ConnectionMenu", () => {
  it("shows отвечает when the card is running and chat is up", async () => {
    const user = userEvent.setup();
    render(<ConnectionMenu />);
    await user.click(await screen.findByRole("button", { name: /подключение/i }));
    expect(await screen.findByText("отвечает")).toBeInTheDocument();
    expect(screen.getByText("не задан")).toBeInTheDocument();
  });

  it("does not stop until Да", async () => {
    const user = userEvent.setup();
    render(<ConnectionMenu />);
    await user.click(await screen.findByRole("button", { name: /подключение/i }));
    await user.click(await screen.findByRole("button", { name: /^остановить$/i }));
    expect(api.gpu.stop).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: /^нет$/i }));
    expect(api.gpu.stop).not.toHaveBeenCalled();
  });
});
