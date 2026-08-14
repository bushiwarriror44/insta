import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../../context/ToastContext";
import { InstagramBrowserPanel } from "../InstagramBrowserPanel";

const apiMock = vi.hoisted(() => ({
  browserStatus: vi.fn().mockResolvedValue({
    username: "alice",
    status: "running",
    awaiting_code: false,
    vnc_path: "api/accounts/alice/browser/vnc/ws",
    account_username: "alice",
    account_login: "alice@mail.com",
    account_password: "secret123",
    account_notes: "test note",
  }),
  browserStart: vi.fn(),
  browserSave: vi.fn(),
  browserStop: vi.fn(),
  browserSubmitCode: vi.fn(),
  browserOpenInstagram: vi.fn(),
  updateNotes: vi.fn(),
  getTotp: vi.fn(),
}));

vi.mock("../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../api/client")>("../../api/client");
  return {
    ...actual,
    api: {
      ...actual.api,
      accounts: {
        ...actual.api.accounts,
        ...apiMock,
      },
    },
  };
});

vi.mock("../DiagnosticLogPanel", async () => {
  const actual = await vi.importActual<typeof import("../DiagnosticLogPanel")>(
    "../DiagnosticLogPanel"
  );
  return {
    ...actual,
    copyTextToClipboard: vi.fn().mockResolvedValue(true),
  };
});

describe("InstagramBrowserPanel", () => {
  beforeEach(() => {
    apiMock.browserSave.mockReset();
    apiMock.updateNotes.mockReset();
    apiMock.getTotp.mockReset();
    apiMock.getTotp.mockResolvedValue({
      totp_seed: "JBSWY3DPEHPK3PXP",
      code: "654321",
      seconds_remaining: 18,
    });
    apiMock.browserStatus.mockResolvedValue({
      username: "alice",
      status: "running",
      awaiting_code: false,
      vnc_path: "api/accounts/alice/browser/vnc/ws",
      account_username: "alice",
      account_login: "alice@mail.com",
      account_password: "secret123",
      account_notes: "test note",
    });
  });

  it("shows diagnostic logs from browser status", async () => {
    apiMock.browserStatus.mockResolvedValue({
      username: "alice",
      status: "running",
      awaiting_code: false,
      vnc_path: "api/accounts/alice/browser/vnc/ws",
      page_url: "https://www.instagram.com/accounts/login/",
      account_username: "alice",
      account_login: "alice@mail.com",
      account_password: "secret123",
      account_notes: "test note",
      logs: [
        {
          ts: "2026-08-09T12:00:00Z",
          level: "info",
          step: "goto",
          message: "Автопереход на Instagram",
        },
      ],
    });

    render(
      <ToastProvider>
        <InstagramBrowserPanel username="alice" adminToken="tok" />
      </ToastProvider>
    );

    expect(await screen.findByText(/Автопереход на Instagram/i)).toBeInTheDocument();
    expect(screen.getByText(/instagram.com\/accounts\/login/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Копировать лог/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Reels$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Лента$/i })).toBeInTheDocument();
    expect(screen.getByText(/Быстрый переход в Instagram/i)).toBeInTheDocument();
  });

  it("shows live TOTP code and copy buttons", async () => {
    const { copyTextToClipboard } = await import("../DiagnosticLogPanel");
    const copySpy = vi.mocked(copyTextToClipboard);
    copySpy.mockResolvedValue(true);

    render(
      <ToastProvider>
        <InstagramBrowserPanel username="alice" adminToken="tok" />
      </ToastProvider>
    );

    expect(await screen.findByText("654321")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Копировать код/i })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Копировать секретный ключ TOTP/i })
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Копировать код/i }));
    await waitFor(() => {
      expect(copySpy).toHaveBeenCalledWith("654321");
    });
    expect(await screen.findByText(/Код TOTP скопирован/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Код подтверждения/i)).toHaveValue("654321");
  });

  it("saves account notes", async () => {
    apiMock.updateNotes.mockResolvedValueOnce({
      username: "alice",
      notes: "saved note",
    });

    render(
      <ToastProvider>
        <InstagramBrowserPanel username="alice" adminToken="tok" />
      </ToastProvider>
    );

    const notes = await screen.findByLabelText(/Заметки/i);
    fireEvent.change(notes, { target: { value: "saved note" } });
    fireEvent.click(screen.getByRole("button", { name: /Сохранить заметки/i }));

    await waitFor(() => {
      expect(apiMock.updateNotes).toHaveBeenCalledWith("alice", { notes: "saved note" });
    });
  });

  it("calls onSessionSaved after successful save in setup mode", async () => {
    const onSessionSaved = vi.fn();
    apiMock.browserSave.mockResolvedValueOnce({
      username: "alice",
      status: "saved",
      awaiting_code: false,
      session_imported: true,
      session_id_saved: true,
      overall_ok: true,
      connection_test: { overall_ok: true, logs: [] },
    });

    render(
      <ToastProvider>
        <InstagramBrowserPanel
          username="alice"
          mode="setup"
          onSessionSaved={onSessionSaved}
        />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Сохранить сессию/i })).not.toBeDisabled();
    });
    fireEvent.click(screen.getByRole("button", { name: /Сохранить сессию/i }));

    await waitFor(() => {
      expect(apiMock.browserSave).toHaveBeenCalledWith("alice", { stopAfterSave: false });
      expect(onSessionSaved).toHaveBeenCalled();
    });
  });

  it("shows blank-page warning when running on about:blank without session.warning", async () => {
    apiMock.browserStatus.mockResolvedValue({
      username: "alice",
      status: "running",
      awaiting_code: false,
      vnc_path: "api/accounts/alice/browser/vnc/ws",
      page_url: "about:blank",
      account_username: "alice",
      account_login: "alice@mail.com",
      account_password: "secret123",
      account_notes: null,
    });

    render(
      <ToastProvider>
        <InstagramBrowserPanel username="alice" adminToken="tok" />
      </ToastProvider>
    );

    expect(
      await screen.findByText(/страница пустая — нажмите «открыть instagram»/i)
    ).toBeInTheDocument();
  });

  it("disables start when hasProxy is false", async () => {
    render(
      <ToastProvider>
        <InstagramBrowserPanel username="alice" adminToken="tok" hasProxy={false} />
      </ToastProvider>
    );

    const start = await screen.findByRole("button", { name: /Запустить браузер/i });
    expect(start).toBeDisabled();
    expect(screen.getByText(/Сначала назначьте прокси/i)).toBeInTheDocument();
    expect(apiMock.browserStart).not.toHaveBeenCalled();
  });

  it("shows TOTP seed missing hint when awaiting code and seed absent", async () => {
    const { ApiError } = await import("../../api/client");
    apiMock.getTotp.mockRejectedValue(new ApiError(404, "TOTP seed не задан для этого аккаунта"));
    apiMock.browserStatus.mockResolvedValue({
      username: "alice",
      status: "awaiting_code",
      awaiting_code: true,
      vnc_path: "api/accounts/alice/browser/vnc/ws",
      page_url: "https://www.instagram.com/accounts/login/",
      account_username: "alice",
      account_login: "alice@mail.com",
      account_password: "secret123",
      account_notes: null,
    });

    render(
      <ToastProvider>
        <InstagramBrowserPanel username="alice" adminToken="tok" />
      </ToastProvider>
    );

    expect(
      await screen.findByText(/TOTP seed не задан — добавьте в настройках аккаунта/i)
    ).toBeInTheDocument();
  });
});
