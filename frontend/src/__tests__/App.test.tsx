import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "../App";

const useAuthMock = vi.hoisted(() => vi.fn());

vi.mock("../context/AuthContext", () => ({
  useAuth: useAuthMock,
  AuthProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("../pages/Login", () => ({
  Login: () => <div>LOGIN_PAGE</div>,
}));
vi.mock("../pages/Dashboard", () => ({
  Dashboard: () => <div>DASHBOARD_PAGE</div>,
}));
vi.mock("../pages/Accounts", () => ({
  Accounts: () => <div>ACCOUNTS_PAGE</div>,
}));
vi.mock("../pages/Upload", () => ({
  Upload: () => <div>UPLOAD_ALIAS</div>,
}));
vi.mock("../pages/Publishing", () => ({
  Publishing: () => <div>PUBLISHING_PAGE</div>,
}));
vi.mock("../pages/Activity", () => ({
  Activity: () => <div>ACTIVITY_PAGE</div>,
}));
vi.mock("../pages/Agent", () => ({
  Agent: () => <div>AGENT_PAGE</div>,
}));
vi.mock("../pages/Renders", () => ({
  Renders: () => <div>RENDERS_PAGE</div>,
}));
vi.mock("../pages/Calendar", () => ({
  Calendar: () => <div>CALENDAR_PAGE</div>,
}));
vi.mock("../pages/Maintenance", () => ({
  Maintenance: () => <div>MAINTENANCE_PAGE</div>,
}));
vi.mock("../pages/Operators", () => ({
  Operators: () => <div>OPERATORS_PAGE</div>,
}));
vi.mock("../pages/Settings", () => ({
  Settings: () => <div>SETTINGS_PAGE</div>,
}));
vi.mock("../pages/Administration", () => ({
  Administration: () => <div>ADMINISTRATION_PAGE</div>,
}));

vi.mock("../context/ToastContext", () => ({
  useToast: () => ({ push: vi.fn() }),
  ToastProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("../api/client", () => ({
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

vi.mock("../components/Assistant", () => ({
  Assistant: () => <div data-testid="assistant-dock" />,
}));

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>
  );
}

beforeEach(() => {
  useAuthMock.mockReset();
});

describe("App routing", () => {
  it("renders the connecting loader while AuthContext is loading", () => {
    useAuthMock.mockReturnValue({
      state: { state: "loading" },
      authRequired: false,
      logout: vi.fn(),
      login: vi.fn(),
      retryBootstrap: vi.fn(),
    });
    renderAt("/");
    expect(screen.getByText(/подключение к api/i)).toBeInTheDocument();
  });

  it("shows API unavailable screen with retry on error state", () => {
    const retryBootstrap = vi.fn();
    useAuthMock.mockReturnValue({
      state: { state: "error", message: "connection refused" },
      authRequired: false,
      logout: vi.fn(),
      login: vi.fn(),
      retryBootstrap,
    });
    renderAt("/");
    expect(screen.getByRole("heading", { name: /api недоступен/i })).toBeInTheDocument();
    expect(screen.getByText(/connection refused/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /повторить/i }));
    expect(retryBootstrap).toHaveBeenCalledTimes(1);
  });

  it("redirects unauthenticated users to /login", () => {
    useAuthMock.mockReturnValue({
      state: { state: "needs-login" },
      authRequired: true,
      logout: vi.fn(),
      login: vi.fn(),
      retryBootstrap: vi.fn(),
    });
    renderAt("/accounts");
    expect(screen.getByText("LOGIN_PAGE")).toBeInTheDocument();
  });

  it("renders the dashboard for an authed/open user at the index route", () => {
    useAuthMock.mockReturnValue({
      state: { state: "open" },
      authRequired: false,
      logout: vi.fn(),
      login: vi.fn(),
      retryBootstrap: vi.fn(),
    });
    renderAt("/");
    expect(screen.getByText("DASHBOARD_PAGE")).toBeInTheDocument();
  });

  it("renders the accounts page when at /accounts", () => {
    useAuthMock.mockReturnValue({
      state: { state: "authed", token: "tok" },
      authRequired: true,
      logout: vi.fn(),
      login: vi.fn(),
      retryBootstrap: vi.fn(),
    });
    renderAt("/accounts");
    expect(screen.getByText("ACCOUNTS_PAGE")).toBeInTheDocument();
  });

  it("redirects /upload to /publishing", () => {
    useAuthMock.mockReturnValue({
      state: { state: "open" },
      authRequired: false,
      logout: vi.fn(),
      login: vi.fn(),
      retryBootstrap: vi.fn(),
    });
    renderAt("/upload");
    expect(screen.getByText("PUBLISHING_PAGE")).toBeInTheDocument();
  });

  it("renders Publishing at /publishing", () => {
    useAuthMock.mockReturnValue({
      state: { state: "open" },
      authRequired: false,
      logout: vi.fn(),
      login: vi.fn(),
      retryBootstrap: vi.fn(),
    });
    renderAt("/publishing");
    expect(screen.getByText("PUBLISHING_PAGE")).toBeInTheDocument();
  });

  it("renders Activity at /activity", () => {
    useAuthMock.mockReturnValue({
      state: { state: "open" },
      authRequired: false,
      logout: vi.fn(),
      login: vi.fn(),
      retryBootstrap: vi.fn(),
    });
    renderAt("/activity");
    expect(screen.getByText("ACTIVITY_PAGE")).toBeInTheDocument();
  });

  it("renders Agent at /agent", () => {
    useAuthMock.mockReturnValue({
      state: { state: "open" },
      authRequired: false,
      logout: vi.fn(),
      login: vi.fn(),
      retryBootstrap: vi.fn(),
    });
    renderAt("/agent");
    expect(screen.getByText("AGENT_PAGE")).toBeInTheDocument();
  });

  it("renders Calendar at /calendar", () => {
    useAuthMock.mockReturnValue({
      state: { state: "open" },
      authRequired: false,
      logout: vi.fn(),
      login: vi.fn(),
      retryBootstrap: vi.fn(),
    });
    renderAt("/calendar");
    expect(screen.getByText("CALENDAR_PAGE")).toBeInTheDocument();
  });

  it("renders Maintenance at /maintenance", () => {
    useAuthMock.mockReturnValue({
      state: { state: "open" },
      authRequired: false,
      logout: vi.fn(),
      login: vi.fn(),
      retryBootstrap: vi.fn(),
    });
    renderAt("/maintenance");
    expect(screen.getByText("MAINTENANCE_PAGE")).toBeInTheDocument();
  });

  it("renders Administration at /administration", () => {
    useAuthMock.mockReturnValue({
      state: { state: "open" },
      authRequired: false,
      logout: vi.fn(),
      login: vi.fn(),
      retryBootstrap: vi.fn(),
    });
    renderAt("/administration");
    expect(screen.getByText("ADMINISTRATION_PAGE")).toBeInTheDocument();
  });

  it("renders Renders at /renders", () => {
    useAuthMock.mockReturnValue({
      state: { state: "open" },
      authRequired: false,
      logout: vi.fn(),
      login: vi.fn(),
      retryBootstrap: vi.fn(),
    });
    renderAt("/renders");
    expect(screen.getByText("RENDERS_PAGE")).toBeInTheDocument();
  });

  it("redirects unknown routes to dashboard when authed", () => {
    useAuthMock.mockReturnValue({
      state: { state: "open" },
      authRequired: false,
      logout: vi.fn(),
      login: vi.fn(),
      retryBootstrap: vi.fn(),
    });
    renderAt("/something/random");
    expect(screen.getByText("DASHBOARD_PAGE")).toBeInTheDocument();
  });
});
