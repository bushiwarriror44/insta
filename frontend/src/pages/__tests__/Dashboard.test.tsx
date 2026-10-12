import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
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
    <MemoryRouter>
      <ToastProvider>
        <Dashboard />
      </ToastProvider>
    </MemoryRouter>
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

  it("links review, failures and agent questions when they need attention", async () => {
    apiMock.dashboard.mockResolvedValue(
      summary({ jobs_awaiting_review: 3, jobs_failed_24h: 4, open_questions: 2 })
    );
    renderDashboard();
    expect(await screen.findByRole("link", { name: /на проверке/i })).toHaveAttribute(
      "href",
      "/activity?status=awaiting_review"
    );
    expect(screen.getByRole("link", { name: /ошибки за 24 часа/i })).toHaveAttribute(
      "href",
      "/activity?status=errors"
    );
    expect(screen.getByRole("link", { name: /вопросы агента/i })).toHaveAttribute("href", "/agent");
  });

  it("deep-links agent questions to the account with open questions", async () => {
    apiMock.dashboard.mockResolvedValue(
      summary({ open_questions: 2, questions_account_id: 7 })
    );
    renderDashboard();
    expect(await screen.findByRole("link", { name: /вопросы агента/i })).toHaveAttribute(
      "href",
      "/agent?account=7"
    );
  });

  it("deep-links quarantined accounts to the cooldown filter", async () => {
    apiMock.dashboard.mockResolvedValue(summary({ quarantined_accounts: 2 }));
    renderDashboard();
    expect(await screen.findByRole("link", { name: /карантин/i })).toHaveAttribute(
      "href",
      "/accounts?status=cooldown"
    );
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
    expect(screen.getByRole("link", { name: /challenge/i })).toHaveAttribute(
      "href",
      "/accounts?username=alice"
    );
    expect(
      screen.getAllByRole("link", { name: /@alice/ }).some((el) =>
        el.getAttribute("href")?.includes("/accounts?username=alice")
      )
    ).toBe(true);
  });

  it("links an event with account id but no username to the account row", async () => {
    apiMock.dashboard.mockResolvedValue(
      summary({
        recent_events: [
          {
            id: 8,
            account_id: 10,
            account_username: null,
            level: "error",
            kind: "publish_failed",
            message: "proxy timeout",
            created_at: new Date().toISOString(),
          },
        ],
      })
    );
    renderDashboard();
    expect(await screen.findByRole("link", { name: /publish_failed/i })).toHaveAttribute(
      "href",
      "/accounts?id=10"
    );
  });

  it("links stat cards into the matching lists", async () => {
    apiMock.dashboard.mockResolvedValue(summary());
    renderDashboard();
    await screen.findByText("Активные аккаунты");
    expect(screen.getByRole("link", { name: "Активные аккаунты" })).toHaveAttribute(
      "href",
      "/accounts"
    );
    expect(screen.getByRole("link", { name: "Исправные прокси" })).toHaveAttribute(
      "href",
      "/accounts?proxy=bad"
    );
    expect(screen.getByRole("link", { name: "В очереди / В работе" })).toHaveAttribute(
      "href",
      "/activity?status=queued"
    );
    expect(screen.getByRole("link", { name: "Мёртвые задачи (всего)" })).toHaveAttribute(
      "href",
      "/activity?status=dead"
    );
  });

  it("links healthy proxies card to accounts without a filter", async () => {
    apiMock.dashboard.mockResolvedValue(
      summary({ proxies_healthy: 3, proxies_total: 3 })
    );
    renderDashboard();
    expect(await screen.findByRole("link", { name: "Исправные прокси" })).toHaveAttribute(
      "href",
      "/accounts"
    );
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
