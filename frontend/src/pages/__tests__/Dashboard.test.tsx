import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../../context/ToastContext";
import { Dashboard } from "../Dashboard";
import type { DashboardSummary } from "../../api/types";

const apiMock = vi.hoisted(() => ({
  dashboard: vi.fn(),
}));

vi.mock("../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../api/client")>(
    "../../api/client"
  );
  return {
    ...actual,
    api: { dashboard: apiMock.dashboard },
  };
});

function summary(overrides: Partial<DashboardSummary> = {}): DashboardSummary {
  return {
    accounts_total: 5,
    accounts_active: 3,
    accounts_blocked: 1,
    proxies_healthy: 2,
    proxies_total: 3,
    jobs_queued: 4,
    jobs_running: 1,
    jobs_done_today: 7,
    jobs_dead_total: 2,
    risk_signals_24h: 1,
    quarantined_accounts: 0,
    daily_stats: [],
    recent_events: [],
    ...overrides,
  };
}

beforeEach(() => {
  apiMock.dashboard.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

function renderDashboard() {
  return render(
    <ToastProvider>
      <Dashboard />
    </ToastProvider>
  );
}

describe("Dashboard page", () => {
  it("shows the loader while fetching", () => {
    apiMock.dashboard.mockImplementation(() => new Promise(() => {}));
    renderDashboard();
    expect(screen.getByText(/загрузка/i)).toBeInTheDocument();
  });

  it("renders the four stat cards once data arrives", async () => {
    apiMock.dashboard.mockResolvedValue(summary());
    renderDashboard();

    await waitFor(() =>
      expect(screen.getByText("Активные аккаунты")).toBeInTheDocument()
    );
    expect(screen.getByText("3 / 5")).toBeInTheDocument();
    expect(screen.getByText("Исправные прокси")).toBeInTheDocument();
    expect(screen.getByText("2 / 3")).toBeInTheDocument();
    expect(screen.getByText("В очереди / В работе")).toBeInTheDocument();
    expect(screen.getByText("4 · 1")).toBeInTheDocument();
    expect(screen.getByText("Мёртвые задачи (всего)")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText(/риск 24ч:/i)).toBeInTheDocument();
  });

  it("shows fallback messages when there is no activity", async () => {
    apiMock.dashboard.mockResolvedValue(
      summary({ daily_stats: [], recent_events: [] })
    );
    renderDashboard();
    await screen.findByText(/сегодня активности пока нет/i);
    expect(screen.getByText(/событий пока нет/i)).toBeInTheDocument();
  });

  it("renders today's per-account stats and recent events", async () => {
    apiMock.dashboard.mockResolvedValue(
      summary({
        daily_stats: [{ username: "alice", posts_count: 2, failures_count: 1 }],
        recent_events: [
          {
            id: 7,
            account_id: 1,
            account_username: "alice",
            level: "warn",
            kind: "challenge",
            message: "code requested",
            created_at: new Date().toISOString(),
          },
        ],
      })
    );
    renderDashboard();
    await screen.findAllByText("@alice");
    expect(screen.getByText("challenge")).toBeInTheDocument();
    expect(screen.getByText("code requested")).toBeInTheDocument();
    expect(screen.getAllByText(/сбои/).length).toBeGreaterThanOrEqual(1);
  });

  it("polls the dashboard at the configured interval", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    apiMock.dashboard.mockResolvedValue(summary());
    renderDashboard();
    await waitFor(() => expect(apiMock.dashboard).toHaveBeenCalledTimes(1));
    await vi.advanceTimersByTimeAsync(8000);
    await waitFor(() =>
      expect(apiMock.dashboard.mock.calls.length).toBeGreaterThanOrEqual(2)
    );
  });

  it("shows error UI with retry when the first load fails", async () => {
    apiMock.dashboard.mockRejectedValueOnce(new Error("dashboard down"));
    renderDashboard();

    expect(
      await screen.findByRole("heading", { name: /не удалось загрузить панель/i })
    ).toBeInTheDocument();
    expect(screen.queryByText(/загрузка/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /повторить/i })).toBeInTheDocument();

    apiMock.dashboard.mockResolvedValueOnce(summary());
    fireEvent.click(screen.getByRole("button", { name: /повторить/i }));

    await waitFor(() =>
      expect(screen.getByText("Активные аккаунты")).toBeInTheDocument()
    );
    expect(apiMock.dashboard.mock.calls.length).toBeGreaterThanOrEqual(2);
  });
});
