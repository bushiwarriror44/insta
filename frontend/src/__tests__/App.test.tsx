import { render, screen } from "@testing-library/react";
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
    });
    renderAt("/");
    expect(screen.getByText(/connecting to api/i)).toBeInTheDocument();
  });

  it("redirects unauthenticated users to /login", () => {
    useAuthMock.mockReturnValue({
      state: { state: "needs-login" },
      authRequired: true,
      logout: vi.fn(),
      login: vi.fn(),
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
    });
    renderAt("/activity");
    expect(screen.getByText("ACTIVITY_PAGE")).toBeInTheDocument();
  });

  it("redirects unknown routes to dashboard when authed", () => {
    useAuthMock.mockReturnValue({
      state: { state: "open" },
      authRequired: false,
      logout: vi.fn(),
      login: vi.fn(),
    });
    renderAt("/something/random");
    expect(screen.getByText("DASHBOARD_PAGE")).toBeInTheDocument();
  });
});
