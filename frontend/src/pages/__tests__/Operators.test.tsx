import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../../context/ToastContext";
import { Operators } from "../Operators";

const useAuthMock = vi.hoisted(() => vi.fn());
const apiMock = vi.hoisted(() => ({
  list: vi.fn(),
  create: vi.fn(),
  revoke: vi.fn(),
}));

vi.mock("../../context/AuthContext", () => ({
  useAuth: useAuthMock,
}));

vi.mock("../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../api/client")>(
    "../../api/client"
  );
  return {
    ...actual,
    api: {
      ...actual.api,
      operators: apiMock,
    },
  };
});

vi.mock("../../components/DiagnosticLogPanel", async () => {
  const actual = await vi.importActual<typeof import("../../components/DiagnosticLogPanel")>(
    "../../components/DiagnosticLogPanel"
  );
  return {
    ...actual,
    copyTextToClipboard: vi.fn().mockResolvedValue(true),
  };
});

function renderOperators() {
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={["/operators"]}>
        <Routes>
          <Route path="/" element={<div>HOME</div>} />
          <Route path="/operators" element={<Operators />} />
        </Routes>
      </MemoryRouter>
    </ToastProvider>
  );
}

beforeEach(() => {
  useAuthMock.mockReset();
  apiMock.list.mockReset();
  apiMock.create.mockReset();
  apiMock.revoke.mockReset();
  apiMock.list.mockResolvedValue([]);
});

describe("Operators page", () => {
  it("redirects non-owners away", async () => {
    useAuthMock.mockReturnValue({ role: "operator" });
    renderOperators();
    expect(await screen.findByText("HOME")).toBeInTheDocument();
  });

  it("shows nav content for owner and creates operator with one-time password", async () => {
    useAuthMock.mockReturnValue({ role: "owner" });
    apiMock.create.mockResolvedValue({
      id: 1,
      label: "ivan",
      created_at: new Date().toISOString(),
      revoked_at: null,
      last_used_at: null,
      active: true,
      password: "once-only-secret",
    });
    apiMock.list
      .mockResolvedValueOnce([])
      .mockResolvedValue([
        {
          id: 1,
          label: "ivan",
          created_at: new Date().toISOString(),
          revoked_at: null,
          last_used_at: null,
          active: true,
        },
      ]);

    renderOperators();
    expect(await screen.findByRole("heading", { name: /доступы/i })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/метка оператора/i), {
      target: { value: "ivan" },
    });
    fireEvent.click(screen.getByRole("button", { name: /сгенерировать пароль/i }));

    expect(await screen.findByText("once-only-secret")).toBeInTheDocument();
    await waitFor(() => {
      expect(apiMock.create).toHaveBeenCalledWith("ivan");
    });
    expect(screen.getAllByText("ivan").length).toBeGreaterThanOrEqual(1);
  });

  it("revokes an active operator", async () => {
    useAuthMock.mockReturnValue({ role: "owner" });
    const row = {
      id: 7,
      label: "temp",
      created_at: new Date().toISOString(),
      revoked_at: null,
      last_used_at: null,
      active: true,
    };
    apiMock.list.mockResolvedValue([row]);
    apiMock.revoke.mockResolvedValue({ ...row, active: false, revoked_at: new Date().toISOString() });
    vi.spyOn(window, "confirm").mockReturnValue(true);

    renderOperators();
    expect(await screen.findByText("temp")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /отозвать/i }));

    await waitFor(() => {
      expect(apiMock.revoke).toHaveBeenCalledWith(7);
    });
  });
});
