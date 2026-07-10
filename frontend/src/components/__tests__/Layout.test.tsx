import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Layout } from "../Layout";

const useAuthMock = vi.hoisted(() => vi.fn());

vi.mock("../../context/AuthContext", () => ({
  useAuth: useAuthMock,
}));

function renderAt(path = "/") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<div>HOME</div>} />
          <Route path="/accounts" element={<div>ACC</div>} />
          <Route path="/publishing" element={<div>PUB</div>} />
          <Route path="/upload" element={<div>UP</div>} />
          <Route path="/activity" element={<div>ACT</div>} />
        </Route>
      </Routes>
    </MemoryRouter>
  );
}

beforeEach(() => {
  useAuthMock.mockReset();
});

describe("Layout", () => {
  it("renders all sidebar links and the active outlet content", () => {
    useAuthMock.mockReturnValue({
      state: { state: "open" },
      authRequired: false,
      logout: vi.fn(),
      login: vi.fn(),
    });
    renderAt("/accounts");
    expect(screen.getByTestId("nav-dashboard")).toBeInTheDocument();
    expect(screen.getByTestId("nav-accounts")).toBeInTheDocument();
    expect(screen.getByTestId("nav-publishing")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /^upload$/i })).not.toBeInTheDocument();
    expect(screen.getByTestId("nav-activity")).toBeInTheDocument();
    expect(screen.getByText("ACC")).toBeInTheDocument();
  });

  it("shows the open-mode hint when auth is not required", () => {
    useAuthMock.mockReturnValue({
      state: { state: "open" },
      authRequired: false,
      logout: vi.fn(),
      login: vi.fn(),
    });
    renderAt();
    expect(screen.getByText(/открытый режим/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /выйти/i })).not.toBeInTheDocument();
  });

  it("shows logout button only when authed", () => {
    const logout = vi.fn();
    useAuthMock.mockReturnValue({
      state: { state: "authed", token: "tok" },
      authRequired: true,
      logout,
      login: vi.fn(),
    });
    renderAt();
    const logoutBtn = screen.getByRole("button", { name: /выйти/i });
    fireEvent.click(logoutBtn);
    expect(logout).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/открытый режим/i)).not.toBeInTheDocument();
  });
});
