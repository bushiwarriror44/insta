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
  }),
  browserStart: vi.fn(),
  browserSave: vi.fn(),
  browserStop: vi.fn(),
  browserSubmitCode: vi.fn(),
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
    apiMock.browserStatus.mockResolvedValue({
      username: "alice",
      status: "running",
      awaiting_code: false,
      vnc_path: "api/accounts/alice/browser/vnc/ws",
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
