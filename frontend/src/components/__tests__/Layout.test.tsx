import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../../api/client";
import { refreshNavBadges } from "../../lib/uiEvents";
import { Layout } from "../Layout";

const useAuthMock = vi.hoisted(() => vi.fn());

vi.mock("../../context/AuthContext", () => ({
  useAuth: useAuthMock,
}));

vi.mock("../../context/ToastContext", () => ({
  useToast: () => ({ push: vi.fn() }),
}));

vi.mock("../../api/client", () => ({
  api: {
    worker: {
      status: vi.fn().mockResolvedValue({
        running: false,
        ours: false,
        pid: null,
        seen_at: null,
        note: "",
      }),
      start: vi.fn(),
      stop: vi.fn(),
    },
    accounts: { list: vi.fn().mockResolvedValue([]) },
    dashboard: vi.fn().mockResolvedValue({
      jobs_awaiting_review: 0,
      jobs_failed_24h: 0,
      open_questions: 0,
    }),
    jobs: { list: vi.fn().mockResolvedValue([]) },
    videos: { list: vi.fn().mockResolvedValue([]) },
  },
  formatApiError: (err: unknown) => String(err),
}));

vi.mock("../Assistant", () => ({
  Assistant: () => <div data-testid="assistant-dock" />,
}));

function renderAt(path = "/") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<div>HOME</div>} />
          <Route path="/accounts" element={
            <>
              <input data-page-search aria-label="Поиск аккаунтов" />
              <div>ACC</div>
            </>
          } />
          <Route path="/publishing" element={<div>PUB</div>} />
          <Route path="/agent" element={<div>AGENT</div>} />
          <Route path="/renders" element={<div>RENDERS</div>} />
          <Route path="/upload" element={<div>UP</div>} />
          <Route path="/activity" element={<div>ACT</div>} />
          <Route path="/calendar" element={<div>CAL</div>} />
          <Route path="/maintenance" element={<div>MAINT</div>} />
        </Route>
      </Routes>
    </MemoryRouter>
  );
}

beforeEach(() => {
  useAuthMock.mockReset();
  vi.mocked(api.dashboard).mockResolvedValue({
    jobs_awaiting_review: 0,
    jobs_failed_24h: 0,
    open_questions: 0,
  } as never);
});

describe("Layout", () => {
  it("renders all sidebar links and the active outlet content", () => {
    useAuthMock.mockReturnValue({
      state: { state: "open" },
      role: null,
      authRequired: false,
      logout: vi.fn(),
      login: vi.fn(),
      retryBootstrap: vi.fn(),
    });
    renderAt("/accounts");
    expect(screen.getByTestId("nav-dashboard")).toBeInTheDocument();
    expect(screen.getByTestId("nav-accounts")).toBeInTheDocument();
    expect(screen.getByTestId("nav-publishing")).toBeInTheDocument();
    expect(screen.getByTestId("nav-agent")).toBeInTheDocument();
    expect(screen.getByTestId("nav-renders")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /^upload$/i })).not.toBeInTheDocument();
    expect(screen.getByTestId("nav-activity")).toBeInTheDocument();
    expect(screen.getByTestId("nav-calendar")).toBeInTheDocument();
    expect(screen.getByTestId("nav-maintenance")).toBeInTheDocument();
    expect(screen.getByTestId("nav-administration")).toBeInTheDocument();
    expect(screen.queryByTestId("nav-operators")).not.toBeInTheDocument();
    expect(screen.getByText("ACC")).toBeInTheDocument();
  });

  it("shows operators and settings nav only for owner role", () => {
    useAuthMock.mockReturnValue({
      state: { state: "authed", token: "tok" },
      role: "owner",
      authRequired: true,
      logout: vi.fn(),
      login: vi.fn(),
      retryBootstrap: vi.fn(),
    });
    renderAt();
    expect(screen.getByTestId("nav-operators")).toBeInTheDocument();
    expect(screen.getByTestId("nav-settings")).toBeInTheDocument();
    expect(screen.getByTestId("nav-administration")).toBeInTheDocument();
  });

  it("hides operators nav for operator role", () => {
    useAuthMock.mockReturnValue({
      state: { state: "authed", token: "tok" },
      role: "operator",
      authRequired: true,
      logout: vi.fn(),
      login: vi.fn(),
      retryBootstrap: vi.fn(),
    });
    renderAt();
    expect(screen.queryByTestId("nav-operators")).not.toBeInTheDocument();
    expect(screen.queryByTestId("nav-settings")).not.toBeInTheDocument();
    expect(screen.queryByTestId("nav-administration")).not.toBeInTheDocument();
  });

  it("shows the open-mode hint when auth is not required", () => {
    useAuthMock.mockReturnValue({
      state: { state: "open" },
      role: null,
      authRequired: false,
      logout: vi.fn(),
      login: vi.fn(),
      retryBootstrap: vi.fn(),
    });
    renderAt();
    expect(screen.getByText(/открытый режим/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /выйти/i })).not.toBeInTheDocument();
  });

  it("shows logout button only when authed", () => {
    const logout = vi.fn();
    useAuthMock.mockReturnValue({
      state: { state: "authed", token: "tok" },
      role: "owner",
      authRequired: true,
      logout,
      login: vi.fn(),
      retryBootstrap: vi.fn(),
    });
    renderAt();
    const logoutBtn = screen.getByRole("button", { name: /выйти/i });
    fireEvent.click(logoutBtn);
    expect(logout).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/открытый режим/i)).not.toBeInTheDocument();
  });

  it("shows nav badges from the dashboard summary", async () => {
    vi.mocked(api.dashboard).mockResolvedValue({
      jobs_awaiting_review: 3,
      jobs_failed_24h: 4,
      open_questions: 2,
    } as never);
    useAuthMock.mockReturnValue({
      state: { state: "open" },
      role: null,
      authRequired: false,
      logout: vi.fn(),
      login: vi.fn(),
      retryBootstrap: vi.fn(),
    });
    renderAt();
    expect(await screen.findByText(/ошибки 24ч: 4/)).toBeInTheDocument();
    expect(screen.getByTestId("nav-activity")).toHaveTextContent("3");
    expect(screen.getByTestId("nav-agent")).toHaveTextContent("2");
  });

  it("refreshes the agent badge when nav badges are invalidated", async () => {
    vi.mocked(api.dashboard)
      .mockResolvedValueOnce({
        jobs_awaiting_review: 0,
        jobs_failed_24h: 0,
        open_questions: 2,
      } as never)
      .mockResolvedValue({
        jobs_awaiting_review: 0,
        jobs_failed_24h: 0,
        open_questions: 0,
      } as never);
    useAuthMock.mockReturnValue({
      state: { state: "open" },
      role: null,
      authRequired: false,
      logout: vi.fn(),
      login: vi.fn(),
      retryBootstrap: vi.fn(),
    });
    renderAt();
    expect(await screen.findByTestId("nav-agent")).toHaveTextContent("2");
    refreshNavBadges();
    await waitFor(() => expect(screen.getByTestId("nav-agent")).not.toHaveTextContent("2"));
  });

  it("opens the command palette from the header", () => {
    useAuthMock.mockReturnValue({
      state: { state: "open" },
      role: null,
      authRequired: false,
      logout: vi.fn(),
      login: vi.fn(),
      retryBootstrap: vi.fn(),
    });
    renderAt();
    fireEvent.click(screen.getByRole("button", { name: /перейти/i }));
    expect(screen.getByTestId("palette-backdrop")).toBeInTheDocument();
  });

  it("opens the command palette with Ctrl+K", () => {
    useAuthMock.mockReturnValue({
      state: { state: "open" },
      role: null,
      authRequired: false,
      logout: vi.fn(),
      login: vi.fn(),
      retryBootstrap: vi.fn(),
    });
    renderAt();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(screen.getByTestId("palette-backdrop")).toBeInTheDocument();
  });

  it("opens the shortcut cheat sheet with ?", () => {
    useAuthMock.mockReturnValue({
      state: { state: "open" },
      role: null,
      authRequired: false,
      logout: vi.fn(),
      login: vi.fn(),
      retryBootstrap: vi.fn(),
    });
    renderAt();
    fireEvent.keyDown(window, { key: "?" });
    expect(screen.getByRole("heading", { name: /клавиши/i })).toBeInTheDocument();
  });

  it("focuses page search with / when a search field exists", () => {
    useAuthMock.mockReturnValue({
      state: { state: "open" },
      role: null,
      authRequired: false,
      logout: vi.fn(),
      login: vi.fn(),
      retryBootstrap: vi.fn(),
    });
    renderAt("/accounts");
    fireEvent.keyDown(window, { key: "/" });
    expect(screen.getByLabelText("Поиск аккаунтов")).toHaveFocus();
    expect(screen.queryByTestId("palette-backdrop")).not.toBeInTheDocument();
  });
});
