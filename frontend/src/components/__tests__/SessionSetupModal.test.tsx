import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../../context/ToastContext";
import { ApiError } from "../../api/client";
import {
  isSessionExpired,
  isSessionMissing,
  SessionSetupModal,
} from "../SessionSetupModal";

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
    browserStatus: vi.fn().mockResolvedValue({
      username: "alice",
      status: "stopped",
      awaiting_code: false,
    }),
    browserStart: vi.fn(),
    browserSave: vi.fn(),
    browserStop: vi.fn(),
    browserSubmitCode: vi.fn(),
  },
}));

vi.mock("../../context/AuthContext", () => ({
  useAuth: () => ({ state: { state: "open" } }),
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
  it("renders connection method choice screen first", () => {
    renderModal();
    expect(screen.getByText(/Режим браузера/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Мобильный/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Десктоп/i })).toBeInTheDocument();
    expect(screen.getByText(/Выберите способ подключения/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Автоматически/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Через браузер/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Создать сессию/i })).not.toBeInTheDocument();
  });

  it("passes desktop surface to firstLogin when selected", async () => {
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
    fireEvent.click(screen.getByRole("button", { name: /Десктоп/i }));
    fireEvent.click(screen.getByRole("button", { name: /Автоматически/i }));
    fireEvent.click(screen.getByRole("button", { name: /Создать сессию/i }));
    await waitFor(() =>
      expect(apiMock.accounts.firstLogin).toHaveBeenCalledWith("alice", { loginSurface: "desktop" })
    );
  });

  it("calls firstLogin for YouTube studio auto mode", async () => {
    apiMock.accounts.firstLogin.mockResolvedValue({
      run_id: 2,
      ok: true,
      challenge: false,
      session_imported: true,
      logs: [],
    });
    render(
      <ToastProvider>
        <SessionSetupModal
          account={{ ...account, platform: "youtube" } as never}
          open
          onClose={vi.fn()}
          onCompleted={vi.fn()}
        />
      </ToastProvider>
    );
    fireEvent.click(screen.getByRole("button", { name: /Автоматически/i }));
    fireEvent.click(screen.getByRole("button", { name: /Создать сессию/i }));
    await waitFor(() =>
      expect(apiMock.accounts.firstLogin).toHaveBeenCalledWith("alice", { loginSurface: "mobile" })
    );
  });

  it("calls firstLogin after choosing auto mode", async () => {
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
    fireEvent.click(screen.getByRole("button", { name: /Автоматически/i }));
    fireEvent.click(screen.getByRole("button", { name: /Создать сессию/i }));
    await waitFor(() =>
      expect(apiMock.accounts.firstLogin).toHaveBeenCalledWith("alice", { loginSurface: "mobile" })
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Готово/i })).toBeInTheDocument()
    );
  });

  it("disables Done on browser path until session saved", async () => {
    renderModal();
    fireEvent.click(screen.getByRole("button", { name: /Через браузер/i }));
    const doneBtn = screen.getByRole("button", { name: /Готово/i });
    expect(doneBtn).toBeDisabled();
    expect(screen.getByRole("button", { name: /Запустить браузер/i })).toBeInTheDocument();
  });

  it("switches to browser mode on challenge from auto", async () => {
    apiMock.accounts.firstLogin.mockResolvedValue({
      run_id: 2,
      ok: false,
      challenge: true,
      browser_tab_hint: true,
      session_imported: false,
      error: "challenge",
      logs: [],
    });
    renderModal();
    fireEvent.click(screen.getByRole("button", { name: /Автоматически/i }));
    fireEvent.click(screen.getByRole("button", { name: /Создать сессию/i }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Запустить браузер/i })).toBeInTheDocument()
    );
  });

  it("shows helpful toast on 405 Method Not Allowed", async () => {
    apiMock.accounts.firstLogin.mockRejectedValue(
      new ApiError(405, "Method Not Allowed")
    );
    renderModal();
    fireEvent.click(screen.getByRole("button", { name: /Автоматически/i }));
    fireEvent.click(screen.getByRole("button", { name: /Создать сессию/i }));
    await waitFor(() =>
      expect(screen.getByText(/Метод не разрешён \(405\)/i)).toBeInTheDocument()
    );
  });

  it("saves pasted sessionid without auto testConnection", async () => {
    const sessionId = "s".repeat(40);
    apiMock.accounts.updateSession.mockResolvedValue({
      ...account,
      has_session_id: true,
    });
    renderModal();
    fireEvent.click(screen.getByRole("button", { name: /вставить sessionid вручную/i }));
    fireEvent.change(screen.getByPlaceholderText(/sessionid/i), {
      target: { value: sessionId },
    });
    fireEvent.click(screen.getByRole("button", { name: /Сохранить сессию/i }));
    await waitFor(() =>
      expect(apiMock.accounts.updateSession).toHaveBeenCalledWith("alice", {
        session_id: sessionId,
      })
    );
    expect(apiMock.accounts.testConnection).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Готово/i })).toBeEnabled()
    );
  });
});

describe("session auth helpers", () => {
  it("detects session_expired for mobile probe failures", () => {
    expect(
      isSessionExpired({ error_code: "session_expired", error: "session_id недействителен или истёк" })
    ).toBe(true);
    expect(isSessionMissing({ error_code: "session_expired", error: "x" })).toBe(false);
    expect(isSessionExpired({ error_code: "session_missing", error: "Нет session_id в БД" })).toBe(
      false
    );
  });
});
