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

describe("InstagramBrowserPanel", () => {
  beforeEach(() => {
    apiMock.browserSave.mockReset();
    apiMock.updateNotes.mockReset();
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

  it("renders start button and code field", async () => {
    render(
      <ToastProvider>
        <InstagramBrowserPanel username="alice" adminToken="tok" />
      </ToastProvider>
    );
    expect(await screen.findByRole("button", { name: /Запустить браузер/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/Код подтверждения/i)).toBeInTheDocument();
    expect(screen.getByText(/Аккаунт/i)).toBeInTheDocument();
    expect(screen.getByText(/alice@mail.com/)).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByLabelText(/Заметки/i)).toHaveValue("test note");
    });
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
});
