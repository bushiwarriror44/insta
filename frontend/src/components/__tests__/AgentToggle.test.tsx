import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../../api/client";
import { AgentToggle } from "../AgentToggle";

vi.mock("../../api/client", () => ({
  api: {
    worker: {
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

function idle() {
  return { running: false, ours: false, pid: null, seen_at: null, note: "" };
}

beforeEach(() => {
  vi.mocked(api.worker.status).mockResolvedValue(idle());
  push.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("AgentToggle", () => {
  it("offers to start when the agent is stopped", async () => {
    render(<AgentToggle />);
    expect(await screen.findByRole("button", { name: /запустить/i })).toBeInTheDocument();
    expect(screen.getByText(/агент остановлен/i)).toBeInTheDocument();
  });

  it("starts the agent from the panel", async () => {
    vi.mocked(api.worker.start).mockResolvedValue({
      running: true,
      ours: true,
      pid: 4242,
      seen_at: null,
      note: "",
    });
    render(<AgentToggle />);
    await userEvent.click(await screen.findByRole("button", { name: /запустить/i }));
    expect(api.worker.start).toHaveBeenCalledOnce();
    expect(await screen.findByText(/pid 4242/i)).toBeInTheDocument();
  });

  it("asks before stopping a worker the panel started", async () => {
    vi.mocked(api.worker.status).mockResolvedValue({
      running: true,
      ours: true,
      pid: 7,
      seen_at: new Date().toISOString(),
      note: "idle",
    });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<AgentToggle />);
    await userEvent.click(await screen.findByRole("button", { name: /остановить/i }));
    expect(confirm).toHaveBeenCalled();
    expect(api.worker.stop).not.toHaveBeenCalled();
    confirm.mockRestore();
  });

  it("offers to stop only a process the panel started", async () => {
    vi.mocked(api.worker.status).mockResolvedValue({
      running: true,
      ours: true,
      pid: 7,
      seen_at: new Date().toISOString(),
      note: "idle",
    });
    render(<AgentToggle />);
    expect(await screen.findByRole("button", { name: /остановить/i })).toBeInTheDocument();
  });

  it("toasts when a running worker disappears", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(api.worker.status)
      .mockResolvedValueOnce({
        running: true,
        ours: true,
        pid: 1,
        seen_at: new Date().toISOString(),
        note: "",
      })
      .mockResolvedValue(idle());
    render(<AgentToggle compact />);
    await waitFor(() => expect(api.worker.status).toHaveBeenCalledTimes(1));
    await vi.advanceTimersByTimeAsync(8000);
    await waitFor(() =>
      expect(push).toHaveBeenCalledWith(
        "Воркер остановился",
        "error",
        expect.objectContaining({ href: "/activity" })
      )
    );
    vi.useRealTimers();
  });

  it("does not toast death after we stop the worker ourselves", async () => {
    vi.mocked(api.worker.status).mockResolvedValue({
      running: true,
      ours: true,
      pid: 7,
      seen_at: new Date().toISOString(),
      note: "",
    });
    vi.mocked(api.worker.stop).mockResolvedValue(idle());
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<AgentToggle compact />);
    await userEvent.click(await screen.findByRole("button", { name: /стоп/i }));
    await waitFor(() => expect(api.worker.stop).toHaveBeenCalled());
    expect(push).toHaveBeenCalledWith("Агент остановлен", "success");
    expect(push).not.toHaveBeenCalledWith(
      "Воркер остановился",
      "error",
      expect.anything()
    );
    confirm.mockRestore();
  });

  it("does not offer stop in compact mode for a worker started outside the panel", async () => {
    vi.mocked(api.worker.status).mockResolvedValue({
      running: true,
      ours: false,
      pid: null,
      seen_at: new Date().toISOString(),
      note: "idle",
    });
    render(<AgentToggle compact />);
    expect(await screen.findByText(/воркер снаружи/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /стоп/i })).not.toBeInTheDocument();
  });

  it("does not stop a worker started outside the panel", async () => {
    vi.mocked(api.worker.status).mockResolvedValue({
      running: true,
      ours: false,
      pid: null,
      seen_at: new Date().toISOString(),
      note: "idle",
    });
    render(<AgentToggle />);
    expect(await screen.findByText(/воркер docker \/ терминал/i)).toBeInTheDocument();
    expect(screen.getByText(/compose поднимает reels-worker/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /остановить/i })).not.toBeInTheDocument();
  });
});