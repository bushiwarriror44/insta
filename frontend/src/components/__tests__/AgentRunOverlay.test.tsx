import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../../api/client";
import { AgentRunOverlay } from "../AgentRunOverlay";

vi.mock("../../api/client", () => ({
  api: {
    assistantJobs: {
      active: vi.fn(),
      pause: vi.fn(),
      resume: vi.fn(),
      stop: vi.fn(),
      ack: vi.fn(),
    },
  },
}));

function job(overrides: Record<string, unknown> = {}) {
  return {
    id: 4,
    status: "running",
    actor: "owner",
    client_chat_id: "c1",
    prompt: "посчитай аккаунты",
    reply: "",
    error: null,
    note: "Жду Ollama",
    result: null,
    created_at: new Date(Date.now() - 65_000).toISOString(),
    fresh: false,
    acting: false,
    activity: "",
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(api.assistantJobs.active).mockReset();
});

describe("AgentRunOverlay", () => {
  it("stays hidden while the run is only waiting on the model", async () => {
    vi.mocked(api.assistantJobs.active).mockResolvedValue(job());
    render(<AgentRunOverlay />);
    await waitFor(() => expect(api.assistantJobs.active).toHaveBeenCalled());
    expect(screen.queryByTestId("agent-run-overlay")).not.toBeInTheDocument();
    expect(screen.queryByText("Жду Ollama")).not.toBeInTheDocument();
  });

  it("shows the task once the agent acts in the panel", async () => {
    vi.mocked(api.assistantJobs.active).mockResolvedValue(
      job({ acting: true, activity: "действие  list_accounts → 3" }),
    );
    render(<AgentRunOverlay />);
    expect(await screen.findByRole("dialog", { name: "агент работает в панели" })).toBeInTheDocument();
    expect(screen.getByText("Агент работает в панели")).toBeInTheDocument();
    expect(screen.getByText("посчитай аккаунты")).toBeInTheDocument();
    expect(screen.getByText(/list_accounts/)).toBeInTheDocument();
    expect(screen.getByText(/идёт 1 мин/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Перехватить управление" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Остановить выполнение" })).toBeInTheDocument();
  });
});
