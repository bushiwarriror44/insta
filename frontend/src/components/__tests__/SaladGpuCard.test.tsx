import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../../api/client";
import { SaladGpuCard } from "../SaladGpuCard";

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

const push = vi.fn();
vi.mock("../../context/ToastContext", () => ({
  useToast: () => ({ push }),
}));

function idle(overrides: Record<string, unknown> = {}) {
  return {
    configured: false,
    status: null,
    billing: false,
    allocating_count: 0,
    creating_count: 0,
    running_count: 0,
    stopping_count: 0,
    chat_ok: false,
    detail: "Задайте SALAD_API_KEY и имена группы в .env",
    ...overrides,
  };
}

beforeEach(() => {
  push.mockReset();
  vi.mocked(api.gpu.status).mockResolvedValue(idle());
  vi.mocked(api.gpu.start).mockReset();
  vi.mocked(api.gpu.stop).mockReset();
});

describe("SaladGpuCard", () => {
  it("disables Start and Stop when Salad is not configured", async () => {
    render(<SaladGpuCard />);
    expect(await screen.findByRole("heading", { name: /gpu salad/i })).toBeInTheDocument();
    expect(screen.getByText(/задайте salad_api_key/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^start$/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^stop$/i })).toBeDisabled();
  });

  it("starts a stopped group after confirm about re-pull and billing", async () => {
    vi.mocked(api.gpu.status).mockResolvedValue(idle({ configured: true, status: "stopped" }));
    vi.mocked(api.gpu.start).mockResolvedValue(
      idle({ configured: true, status: "deploying", creating_count: 1 })
    );
    render(<SaladGpuCard />);
    expect(await screen.findByText(/stopped — не тарится/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /^start$/i }));
    expect(screen.getByRole("heading", { name: /запустить видеокарту/i })).toBeInTheDocument();
    expect(screen.getByText(/образ снова качается/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /^да$/i }));
    await waitFor(() => expect(api.gpu.start).toHaveBeenCalled());
    expect(await screen.findByText(/качается образ/i)).toBeInTheDocument();
  });

  it("does not start when confirm is cancelled", async () => {
    vi.mocked(api.gpu.status).mockResolvedValue(idle({ configured: true, status: "stopped" }));
    render(<SaladGpuCard />);
    await screen.findByRole("button", { name: /^start$/i });
    await userEvent.click(screen.getByRole("button", { name: /^start$/i }));
    await userEvent.click(screen.getByRole("button", { name: /^нет$/i }));
    expect(api.gpu.start).not.toHaveBeenCalled();
  });

  it("stops a running group after confirm that hours and chat stop", async () => {
    vi.mocked(api.gpu.status).mockResolvedValue(
      idle({
        configured: true,
        status: "running",
        billing: true,
        running_count: 1,
        chat_ok: true,
        idle_stop_minutes: 20,
      })
    );
    vi.mocked(api.gpu.stop).mockResolvedValue(idle({ configured: true, status: "stopped" }));
    render(<SaladGpuCard />);
    expect(await screen.findByText(/running — идут gpu-часы/i)).toBeInTheDocument();
    expect(screen.getByText(/авто-stop через 20 мин простоя/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^start$/i })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: /^stop$/i }));
    expect(screen.getByText(/часы остановятся/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /^да$/i }));
    await waitFor(() => expect(api.gpu.stop).toHaveBeenCalled());
    expect(await screen.findByText(/stopped — не тарится/i)).toBeInTheDocument();
  });

  it("shows статус не обновился when the poll fails", async () => {
    vi.mocked(api.gpu.status).mockRejectedValue(new Error("сеть"));
    render(<SaladGpuCard />);
    expect(await screen.findByText(/статус не обновился/i)).toBeInTheDocument();
    expect(screen.getByText(/сеть/i)).toBeInTheDocument();
  });
});
