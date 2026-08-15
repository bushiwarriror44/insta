import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../../context/ToastContext";
import { Settings } from "../Settings";

const useAuthMock = vi.hoisted(() => vi.fn());
const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  updateEntryPath: vi.fn(),
  updateMasterPassword: vi.fn(),
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
      settings: apiMock,
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

function renderSettings() {
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={["/settings"]}>
        <Routes>
          <Route path="/" element={<div>HOME</div>} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </MemoryRouter>
    </ToastProvider>
  );
}

beforeEach(() => {
  useAuthMock.mockReset();
  apiMock.get.mockReset();
  apiMock.updateEntryPath.mockReset();
  apiMock.updateMasterPassword.mockReset();
  apiMock.get.mockResolvedValue({
    entry_path: "/secretPathValue1",
    master_password_set: false,
  });
});

describe("Settings page", () => {
  it("redirects non-owners", async () => {
    useAuthMock.mockReturnValue({ role: "operator" });
    renderSettings();
    expect(await screen.findByText("HOME")).toBeInTheDocument();
  });

  it("loads settings for owner", async () => {
    useAuthMock.mockReturnValue({ role: "owner" });
    renderSettings();
    expect(await screen.findByRole("heading", { name: /настройки/i })).toBeInTheDocument();
    expect(await screen.findByDisplayValue("/secretPathValue1")).toBeInTheDocument();
  });

  it("submits master password change", async () => {
    useAuthMock.mockReturnValue({ role: "owner" });
    apiMock.updateMasterPassword.mockResolvedValue({
      entry_path: "/secretPathValue1",
      master_password_set: true,
    });
    renderSettings();
    await screen.findByRole("heading", { name: /настройки/i });

    fireEvent.change(screen.getByLabelText(/текущий пароль \/ admin_token/i), {
      target: { value: "old" },
    });
    fireEvent.change(screen.getByLabelText(/^новый пароль$/i), {
      target: { value: "newpass12" },
    });
    fireEvent.change(screen.getByLabelText(/подтверждение/i), {
      target: { value: "newpass12" },
    });
    fireEvent.click(screen.getByRole("button", { name: /сменить мастер-пароль/i }));

    await waitFor(() => {
      expect(apiMock.updateMasterPassword).toHaveBeenCalledWith("old", "newpass12");
    });
  });
});
