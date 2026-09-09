import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../../context/ToastContext";
import type { EventOut, JobOut } from "../../api/types";
import { Activity } from "../Activity";

const apiMock = vi.hoisted(() => ({
  jobs: { list: vi.fn(), cancel: vi.fn(), logs: vi.fn(), approve: vi.fn(), retry: vi.fn() },
  events: { list: vi.fn() },
  factory: {
    generations: vi.fn().mockResolvedValue([]),
    compositions: vi.fn().mockResolvedValue([]),
  },
}));

vi.mock("../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../api/client")>(
    "../../api/client"
  );
  return {
    ...actual,
    api: apiMock,
  };
});

const job: JobOut = {
  id: 42,
  account_id: 1,
  account_username: "alice",
  source_video_path: "/data/videos/source/clip.mp4",
  post_type: "reel",
  caption_template: null,
  scheduled_for: new Date().toISOString(),
  status: "queued",
  attempts: 0,
  last_error: null,
  next_attempt_at: null,
  started_at: null,
  finished_at: null,
  created_at: new Date().toISOString(),
};

const event: EventOut = {
  id: 5,
  account_id: 1,
  account_username: "alice",
  level: "warn",
  kind: "challenge",
  message: "code requested",
  created_at: new Date().toISOString(),
};

beforeEach(() => {
  apiMock.jobs.list.mockReset();
  apiMock.jobs.cancel.mockReset();
  apiMock.jobs.logs.mockReset();
  apiMock.jobs.approve.mockReset();
  apiMock.jobs.retry.mockReset();
  apiMock.events.list.mockReset();
  apiMock.factory.generations.mockReset();
  apiMock.factory.compositions.mockReset();
  apiMock.jobs.list.mockResolvedValue([job]);
  apiMock.jobs.logs.mockResolvedValue([]);
  apiMock.events.list.mockResolvedValue([event]);
  apiMock.factory.generations.mockResolvedValue([]);
  apiMock.factory.compositions.mockResolvedValue([]);
});

function renderActivity(path = "/activity") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ToastProvider>
        <Activity />
      </ToastProvider>
    </MemoryRouter>
  );
}

describe("Activity page", () => {
  it("opens the job log when ?job= is in the URL", async () => {
    renderActivity("/activity?job=42");
    expect(await screen.findByRole("heading", { name: /логи задачи #42/i })).toBeInTheDocument();
  });

  it("does not reopen job logs after close and refresh", async () => {
    renderActivity("/activity?job=42");
    expect(await screen.findByRole("heading", { name: /логи задачи #42/i })).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: /закрыть/i })[0]);
    await waitFor(() => {
      expect(screen.queryByRole("heading", { name: /логи задачи #42/i })).not.toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: /обновить сейчас/i }));
    await waitFor(() => expect(apiMock.jobs.list.mock.calls.length).toBeGreaterThan(1));
    expect(screen.queryByRole("heading", { name: /логи задачи #42/i })).not.toBeInTheDocument();
  });

  it("renders jobs and events tables", async () => {
    renderActivity();
    await screen.findByText("#42");
    // @alice and status badges can match in multiple sections (rows + select options).
    expect(screen.getAllByText("@alice").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("В очереди").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("challenge")).toBeInTheDocument();
    expect(screen.getByText("code requested")).toBeInTheDocument();
  });

  it("filters jobs by status from the URL", async () => {
    renderActivity("/activity?status=queued");
    await waitFor(() =>
      expect(apiMock.jobs.list).toHaveBeenCalledWith(
        expect.objectContaining({ status: "queued", limit: 100 })
      )
    );
    expect(screen.getAllByRole("combobox")[0]).toHaveValue("queued");
  });

  it("filters dead jobs when opened with ?status=dead", async () => {
    renderActivity("/activity?status=dead");
    await waitFor(() =>
      expect(apiMock.jobs.list).toHaveBeenCalledWith(
        expect.objectContaining({ status: "dead", limit: 100 })
      )
    );
    expect(screen.getAllByRole("combobox")[0]).toHaveValue("dead");
  });

  it("filters jobs by status when the dropdown changes", async () => {
    renderActivity();
    await screen.findByText("#42");
    apiMock.jobs.list.mockClear();

    const select = screen.getAllByRole("combobox")[0];
    fireEvent.change(select, { target: { value: "running" } });

    await waitFor(() =>
      expect(apiMock.jobs.list).toHaveBeenCalledWith(
        expect.objectContaining({ status: "running", limit: 100 })
      )
    );
  });

  it("filters events by level", async () => {
    renderActivity();
    await screen.findByText("#42");
    apiMock.events.list.mockClear();

    const selects = screen.getAllByRole("combobox");
    fireEvent.change(selects[1], { target: { value: "error" } });

    await waitFor(() =>
      expect(apiMock.events.list).toHaveBeenCalledWith(
        expect.objectContaining({ level: "error", limit: 100 })
      )
    );
  });

  it("approves a job waiting for review", async () => {
    apiMock.jobs.list.mockResolvedValue([{ ...job, status: "awaiting_review" }]);
    apiMock.jobs.approve.mockResolvedValue({ ...job, status: "queued" });
    renderActivity();
    await screen.findByText("#42");
    fireEvent.click(screen.getByRole("button", { name: /одобрить/i }));
    await waitFor(() => expect(apiMock.jobs.approve).toHaveBeenCalledWith(42));
  });

  it("cancels a queued job from the table", async () => {
    apiMock.jobs.cancel.mockResolvedValue({ ...job, status: "cancelled" });
    renderActivity();
    await screen.findByText("#42");

    const cancelBtn = screen.getByRole("button", { name: /отменить/i });
    fireEvent.click(cancelBtn);
    await waitFor(() => expect(apiMock.jobs.cancel).toHaveBeenCalledWith(42));
  });

  it("does not show cancel button for terminal job statuses", async () => {
    apiMock.jobs.list.mockResolvedValue([{ ...job, status: "done" }]);
    renderActivity();
    await screen.findByText("#42");
    expect(
      screen.queryByRole("button", { name: /отменить/i })
    ).not.toBeInTheDocument();
  });

  it("opens job log modal when clicking a row", async () => {
    apiMock.jobs.logs.mockResolvedValue([
      {
        id: 1,
        kind: "publish_job",
        account_id: 1,
        account_username: "alice",
        job_id: 42,
        status: "fail",
        summary: "proxy unhealthy",
        logs: [
          {
            ts: new Date().toISOString(),
            level: "error",
            step: "proxy",
            message: "timeout",
          },
        ],
        created_at: new Date().toISOString(),
        finished_at: new Date().toISOString(),
      },
    ]);
    renderActivity();
    await screen.findByText("#42");
    fireEvent.click(screen.getByText("#42"));
    await waitFor(() => expect(apiMock.jobs.logs).toHaveBeenCalledWith(42));
    expect(await screen.findByText(/timeout/i)).toBeInTheDocument();
  });

  it("syncs selected job status in the modal after reload", async () => {
    apiMock.jobs.list.mockResolvedValue([{ ...job, status: "running" }]);
    apiMock.jobs.logs.mockResolvedValue([
      {
        id: 1,
        kind: "publish_job",
        account_id: 1,
        account_username: "alice",
        job_id: 42,
        status: "running",
        summary: null,
        logs: [
          {
            ts: new Date().toISOString(),
            level: "info",
            step: "publish",
            message: "uploading",
          },
        ],
        created_at: new Date().toISOString(),
        finished_at: null,
      },
    ]);
    renderActivity();
    await screen.findByText("#42");
    fireEvent.click(screen.getByText("#42"));
    const modalTitle = await screen.findByRole("heading", { name: /логи задачи #42/i });
    const modal = modalTitle.closest("div.card") as HTMLElement;
    expect(within(modal).getByText("В работе")).toBeInTheDocument();

    apiMock.jobs.list.mockResolvedValue([{ ...job, status: "done", attempts: 1 }]);
    fireEvent.click(screen.getByRole("button", { name: /обновить сейчас/i }));

    await waitFor(() => {
      expect(within(modal).getByText("Готово")).toBeInTheDocument();
    });
  });

  it("labels diagnostic run statuses with Russian diag labels", async () => {
    apiMock.jobs.logs.mockResolvedValue([
      {
        id: 1,
        kind: "publish_job",
        account_id: 1,
        account_username: "alice",
        job_id: 42,
        status: "fail",
        summary: "proxy unhealthy",
        logs: [],
        created_at: new Date().toISOString(),
        finished_at: new Date().toISOString(),
      },
      {
        id: 2,
        kind: "publish_job",
        account_id: 1,
        account_username: "alice",
        job_id: 42,
        status: "ok",
        summary: "published",
        logs: [],
        created_at: new Date().toISOString(),
        finished_at: new Date().toISOString(),
      },
    ]);
    renderActivity();
    await screen.findByText("#42");
    fireEvent.click(screen.getByText("#42"));

    expect(await screen.findByRole("option", { name: /попытка 1 — ошибка/i })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /попытка 2 — ok/i })).toBeInTheDocument();
  });

  it("renders empty placeholder when there are no jobs", async () => {
    apiMock.jobs.list.mockResolvedValue([]);
    apiMock.events.list.mockResolvedValue([]);
    renderActivity();
    await screen.findByText(/нет задач по выбранному фильтру/i);
    expect(screen.getByText(/событий нет/i)).toBeInTheDocument();
  });

  it("opens the highlighted job with Enter", async () => {
    renderActivity();
    await screen.findByText("#42");
    fireEvent.keyDown(window, { key: "Enter" });
    expect(await screen.findByRole("heading", { name: /логи задачи #42/i })).toBeInTheDocument();
  });

  it("moves the cursor with j", async () => {
    apiMock.jobs.list.mockResolvedValue([
      job,
      { ...job, id: 43, account_username: "bob" },
    ]);
    renderActivity();
    await screen.findByText("#43");
    fireEvent.keyDown(window, { key: "j" });
    expect(screen.getByRole("row", { name: /задача #43/i }).className).toContain("bg-white");
  });

  it("moves the cursor back with k", async () => {
    apiMock.jobs.list.mockResolvedValue([
      job,
      { ...job, id: 43, account_username: "bob" },
    ]);
    renderActivity();
    await screen.findByText("#43");
    fireEvent.keyDown(window, { key: "j" });
    expect(screen.getByRole("row", { name: /задача #43/i }).className).toContain("bg-white");
    fireEvent.keyDown(window, { key: "k" });
    expect(screen.getByRole("row", { name: /задача #43/i }).className).not.toContain("bg-white");
    expect(screen.getByRole("row", { name: /задача #42/i }).className).toContain("bg-white");
  });

  it("links an event with @user to the account page", async () => {
    renderActivity();
    expect(await screen.findByRole("link", { name: /challenge/i })).toHaveAttribute(
      "href",
      "/accounts?username=alice"
    );
  });

  it("links an event with account id but no username to the account row", async () => {
    apiMock.events.list.mockResolvedValue([
      { ...event, account_id: 10, account_username: null, kind: "publish_failed" },
    ]);
    renderActivity();
    expect(await screen.findByRole("link", { name: /publish_failed/i })).toHaveAttribute(
      "href",
      "/accounts?id=10"
    );
  });

  it("retries a failed job", async () => {
    apiMock.jobs.list.mockResolvedValue([{ ...job, status: "failed" }]);
    apiMock.jobs.retry.mockResolvedValue({ ...job, status: "queued" });
    renderActivity();
    await screen.findByText("#42");
    fireEvent.click(screen.getByRole("button", { name: /повторить/i }));
    await waitFor(() => expect(apiMock.jobs.retry).toHaveBeenCalledWith(42));
  });

  it("loads renders when switching lanes", async () => {
    apiMock.factory.generations.mockResolvedValue([
      { id: 7, status: "queued", prompt: "sunset", post_title: "clip a", last_error: null },
    ]);
    renderActivity();
    await screen.findByText("#42");
    apiMock.factory.generations.mockClear();
    fireEvent.click(screen.getByRole("button", { name: /^рендеры$/i }));
    await waitFor(() => expect(apiMock.factory.generations).toHaveBeenCalled());
    expect(await screen.findByText(/#7/)).toBeInTheDocument();
  });
});
