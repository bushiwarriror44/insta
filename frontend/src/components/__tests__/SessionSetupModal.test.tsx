import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../../context/ToastContext";
import { ApiError } from "../../api/client";
import { SessionSetupModal } from "../SessionSetupModal";

const account = {
  id: 1,
  username: "alice",
  status: "active",
  proxy_label: "px1",
  proxy_country: "US",
  has_session_id: false,
  session_file_exists: false,
  session_source: "none",
} as const;

const apiMock = vi.hoisted(() => ({
  accounts: {
    firstLogin: vi.fn(),
    updateSession: vi.fn(),
    testConnection: vi.fn(),
  },
}));

vi.mock("../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../api/client")>("../../api/client");
  return {
    ...actual,
    api: apiMock,
  };
});

function renderModal(open = true) {
  const onCompleted = vi.fn();
  const onClose = vi.fn();
  render(
    <ToastProvider>
      <SessionSetupModal
        account={account as never}
        open={open}
        onClose={onClose}
        onCompleted={onCompleted}
      />
    </ToastProvider>
  );
  return { onCompleted, onClose };
}

beforeEach(() => {
  apiMock.accounts.firstLogin.mockReset();
  apiMock.accounts.updateSession.mockReset();
  apiMock.accounts.testConnection.mockReset();
});

describe("SessionSetupModal", () => {
  it("renders auto and manual tabs", () => {
    renderModal();
    expect(screen.getByRole("button", { name: /Автовход/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Ручной импорт/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Создать сессию/i })).toBeInTheDocument();
  });

  it("calls firstLogin on auto tab", async () => {
    apiMock.accounts.firstLogin.mockResolvedValue({
      run_id: 1,
      ok: true,
      challenge: false,
      session_imported: true,
      logs: [],
      connection_test: {
        overall_ok: true,
        instagram_auth: {
          ok: true,
          method: "sessionid",
          challenge: false,
          ig_username: "alice",
        },
        logs: [],
      },
    });
    renderModal();
    fireEvent.click(screen.getByRole("button", { name: /Создать сессию/i }));
    await waitFor(() =>
      expect(apiMock.accounts.firstLogin).toHaveBeenCalledWith("alice")
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Готово/i })).toBeInTheDocument()
    );
  });

  it("switches to manual tab on challenge", async () => {
    apiMock.accounts.firstLogin.mockResolvedValue({
      run_id: 2,
      ok: false,
      challenge: true,
      session_imported: false,
      error: "challenge",
      logs: [],
    });
    renderModal();
    fireEvent.click(screen.getByRole("button", { name: /Создать сессию/i }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Ручной импорт/i })).toHaveClass("bg-slate-800")
    );
  });

  it("shows helpful toast on 405 Method Not Allowed", async () => {
    apiMock.accounts.firstLogin.mockRejectedValue(
      new ApiError(405, "Method Not Allowed")
    );
    renderModal();
    fireEvent.click(screen.getByRole("button", { name: /Создать сессию/i }));
    await waitFor(() =>
      expect(screen.getByText(/Метод не разрешён \(405\)/i)).toBeInTheDocument()
    );
  });
});
