import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Agent } from "../Agent";

const apiMock = vi.hoisted(() => ({
  accounts: {
    list: vi.fn(),
  },
  factory: {
    agentRuns: vi.fn(),
    agentRun: vi.fn(),
    plan: vi.fn(),
    week: vi.fn(),
    preview: vi.fn(),
    updateBrief: vi.fn(),
    presets: vi.fn(),
    sources: vi.fn(),
    addSource: vi.fn(),
    patchSource: vi.fn(),
    checkSource: vi.fn(),
    questions: vi.fn(),
    answerQuestion: vi.fn(),
  },
  worker: {
    status: vi.fn(),
    start: vi.fn(),
    stop: vi.fn(),
  },
}));

vi.mock("../../api/client", () => ({
  api: apiMock,
  formatApiError: (err: unknown) => String(err),
}));

vi.mock("../../context/ToastContext", () => ({
  useToast: () => ({ push: vi.fn() }),
}));

const source = {
  id: 4,
  kind: "url",
  value: "https://example.com/feed",
  label: "example",
  enabled: true,
  last_status: "ok",
};

const question = {
  id: 7,
  question: "Какая ниша?",
  why: "бриф пустой",
  assumed: "travel",
  open: true,
};

const run = {
  id: 9,
  account_username: "alice",
  ok: true,
  model: "qwen",
  requested: 5,
  returned: 3,
  cost_usd: 0.12,
  error: null,
  created_at: "2026-09-08T10:00:00Z",
};

function defaults() {
  apiMock.accounts.list.mockResolvedValue([
    { id: 1, username: "alice", platform: "instagram", brief: "nature" },
  ]);
  apiMock.factory.agentRuns.mockResolvedValue([]);
  apiMock.factory.agentRun.mockResolvedValue({
    id: 9,
    ok: true,
    prompt: "plan prompt",
    raw: "",
    ideas: [{ title: "reel" }],
    questions: [],
    sources: [],
    error: null,
    cost_usd: 0.12,
    duration_ms: 10,
  });
  apiMock.factory.plan.mockResolvedValue({ id: 1, status: "queued" });
  apiMock.factory.week.mockResolvedValue({ id: 2, status: "queued" });
  apiMock.factory.preview.mockResolvedValue({ planned: 2 });
  apiMock.factory.updateBrief.mockResolvedValue({ brief: "nature" });
  apiMock.factory.presets.mockResolvedValue([]);
  apiMock.factory.sources.mockResolvedValue([]);
  apiMock.factory.addSource.mockResolvedValue({ id: 4 });
  apiMock.factory.checkSource.mockResolvedValue({ id: 4, last_status: "ok" });
  apiMock.factory.questions.mockResolvedValue([]);
  apiMock.factory.answerQuestion.mockResolvedValue({ id: 7 });
  apiMock.worker.status.mockResolvedValue({
    running: false,
    ours: false,
    pid: null,
    seen_at: null,
    note: "",
  });
}

async function renderReady() {
  render(<Agent />);
  await waitFor(() =>
    expect(screen.getByRole("button", { name: /запланировать/i })).toBeEnabled()
  );
}

describe("Agent page", () => {
  beforeEach(() => {
    Object.values(apiMock.accounts).forEach((fn) => fn.mockReset());
    Object.values(apiMock.factory).forEach((fn) => fn.mockReset());
    Object.values(apiMock.worker).forEach((fn) => fn.mockReset());
    defaults();
  });

  it("renders planner controls", async () => {
    await renderReady();
    expect(screen.getByRole("heading", { name: /контент-агент/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /план на неделю/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /превью/i })).toBeInTheDocument();
  });

  it("queues a plan with count, duration and auto_schedule", async () => {
    await renderReady();
    fireEvent.click(screen.getByRole("button", { name: /запланировать/i }));
    await waitFor(() =>
      expect(apiMock.factory.plan).toHaveBeenCalledWith(1, {
        count: 5,
        duration_s: 5,
        auto_schedule: true,
      })
    );
    expect(apiMock.factory.updateBrief).toHaveBeenCalledWith(1, "nature");
  });

  it("sends auto_schedule=false with the week plan when the checkbox is off", async () => {
    await renderReady();
    fireEvent.click(screen.getByRole("checkbox", { name: /сразу ставить в расписание/i }));
    fireEvent.click(screen.getByRole("button", { name: /план на неделю/i }));
    await waitFor(() =>
      expect(apiMock.factory.week).toHaveBeenCalledWith(1, {
        count: 5,
        duration_s: 5,
        auto_schedule: false,
      })
    );
  });

  it("previews with the form count and duration", async () => {
    await renderReady();
    const count = screen.getByRole("spinbutton", { name: /сколько роликов/i });
    const duration = screen.getByRole("spinbutton", { name: /длительность/i });
    fireEvent.change(count, { target: { value: "8" } });
    fireEvent.change(duration, { target: { value: "7" } });
    fireEvent.click(screen.getByRole("button", { name: /превью/i }));
    await waitFor(() =>
      expect(apiMock.factory.preview).toHaveBeenCalledWith(1, {
        count: 8,
        duration_s: 7,
      })
    );
    expect(apiMock.factory.preview.mock.calls[0][1]).not.toEqual({ count: 3 });
  });

  it("adds a source URL and checks it", async () => {
    let sources: typeof source[] = [];
    apiMock.factory.sources.mockImplementation(async () => sources);
    apiMock.factory.addSource.mockImplementation(async () => {
      sources = [source];
      return { id: 4 };
    });
    await renderReady();
    fireEvent.change(screen.getByPlaceholderText("https://…"), {
      target: { value: "https://example.com/feed" },
    });
    fireEvent.click(screen.getByRole("button", { name: /добавить/i }));
    await waitFor(() =>
      expect(apiMock.factory.addSource).toHaveBeenCalledWith(1, {
        kind: "url",
        value: "https://example.com/feed",
      })
    );
    expect(await screen.findByText("example")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /проверить/i }));
    await waitFor(() => expect(apiMock.factory.checkSource).toHaveBeenCalledWith(4));
  });

  it("answers a question, removes it, and refreshes nav badges", async () => {
    let open = [question];
    apiMock.factory.questions.mockImplementation(async () => open);
    apiMock.factory.answerQuestion.mockImplementation(async () => {
      open = [];
      return { id: 7 };
    });
    const onBadges = vi.fn();
    window.addEventListener("panel-refresh-nav-badges", onBadges);
    await renderReady();
    expect(await screen.findByText("Какая ниша?")).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("Ответ"), { target: { value: "travel vlogs" } });
    fireEvent.click(screen.getByRole("button", { name: /ответить/i }));
    await waitFor(() =>
      expect(apiMock.factory.answerQuestion).toHaveBeenCalledWith(7, "travel vlogs")
    );
    await waitFor(() => expect(screen.queryByText("Какая ниша?")).not.toBeInTheDocument());
    expect(onBadges).toHaveBeenCalled();
    window.removeEventListener("panel-refresh-nav-badges", onBadges);
  });

  it("opens run details from the table", async () => {
    apiMock.factory.agentRuns.mockResolvedValue([run]);
    await renderReady();
    fireEvent.click(await screen.findByText("qwen"));
    expect(await screen.findByRole("heading", { name: /прогон #9/i })).toBeInTheDocument();
    expect(apiMock.factory.agentRun).toHaveBeenCalledWith(9);
    expect(screen.getByText("plan prompt")).toBeInTheDocument();
  });
});
