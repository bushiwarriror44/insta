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
  browserPaste: vi.fn(),
  updateNotes: vi.fn(),
  getTotp: vi.fn(),
  importCookiesFile: vi.fn(),
  testConnection: vi.fn(),
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

/** Vitest/JSDOM does not apply Tailwind responsive `hidden sm:inline-flex`, so duplicate overflow buttons exist. */
function primaryToolbarButton(name: RegExp | string) {
  const matches = screen.getAllByRole("button", { name });
  const desktop = matches.find((el) => (el as HTMLElement).className.includes("hidden sm:inline-flex"));
  return (desktop ?? matches[0]) as HTMLElement;
}

describe("InstagramBrowserPanel", () => {
  beforeEach(() => {
    apiMock.browserSave.mockReset();
    apiMock.updateNotes.mockReset();
    apiMock.getTotp.mockReset();
    apiMock.importCookiesFile.mockReset();
    apiMock.testConnection.mockReset();
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
    expect(screen.getByRole("button", { name: /^Копировать лог$/i })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: /диагностика/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Рилс$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Лента$/i })).toBeInTheDocument();
    expect(screen.getByText(/Быстрый переход в Instagram/i)).toBeInTheDocument();
  });

  it("uses economical noVNC quality and compression in iframe src", async () => {
    render(
      <ToastProvider>
        <InstagramBrowserPanel username="alice" adminToken="tok" />
      </ToastProvider>
    );

    const iframe = await screen.findByTitle(/Браузер VNC Instagram · @alice/i);
    const src = iframe.getAttribute("src") ?? "";
    expect(src).toContain("quality=3");
    expect(src).toContain("compression=8");
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
      expect(screen.getByRole("button", { name: /Сохранить сессию и куки/i })).not.toBeDisabled();
    });
    fireEvent.click(screen.getByRole("button", { name: /Сохранить сессию и куки/i }));

    await waitFor(() => {
      expect(apiMock.browserSave).toHaveBeenCalledWith("alice", { stopAfterSave: false });
      expect(onSessionSaved).toHaveBeenCalled();
    });
  });

  it("calls browserSave with stopAfterSave when using save and stop", async () => {
    apiMock.browserSave.mockResolvedValueOnce({
      username: "alice",
      status: "stopped",
      awaiting_code: false,
      vnc_path: null,
      session_imported: true,
      session_id_saved: true,
      overall_ok: true,
      connection_test: { overall_ok: true, logs: [] },
    });

    render(
      <ToastProvider>
        <InstagramBrowserPanel username="alice" adminToken="tok" />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(primaryToolbarButton(/Сохранить и остановить/i)).not.toBeDisabled();
    });
    fireEvent.click(primaryToolbarButton(/Сохранить и остановить/i));

    await waitFor(() => {
      expect(apiMock.browserSave).toHaveBeenCalledWith("alice", { stopAfterSave: true });
    });
  });

  it("shows Instagram 429 hint when login page returns 429 on about:blank", async () => {
    apiMock.browserStatus.mockResolvedValue({
      username: "alice",
      status: "running",
      awaiting_code: false,
      vnc_path: "api/accounts/alice/browser/vnc/ws",
      page_url: "about:blank",
      proxy_ip: "1.2.3.4",
      proxy_instagram_login_http_status: 429,
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
      await screen.findByText(/Временное ограничение запросов с IP прокси/i)
    ).toBeInTheDocument();
    expect(screen.getByText(/HTTP 429/i)).toBeInTheDocument();
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
    apiMock.getTotp.mockRejectedValue(new ApiError(404, "Секрет TOTP не задан для этого аккаунта"));
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
      await screen.findByText(/Секрет TOTP не задан — добавьте в настройках аккаунта/i)
    ).toBeInTheDocument();
  });

  it("shows Google signin/rejected alert", async () => {
    apiMock.browserStatus.mockResolvedValue({
      username: "ytuser",
      status: "running",
      awaiting_code: false,
      vnc_path: "api/accounts/ytuser/browser/vnc/ws",
      page_url: "https://accounts.google.com/v3/signin/rejected",
      warning:
        "Google отклонил вход («браузер небезопасен»). Смените прокси или войдите вручную в VNC.",
      account_username: "ytuser",
      account_login: "yt@mail.com",
      account_password: "x",
      account_notes: null,
    });

    render(
      <ToastProvider>
        <InstagramBrowserPanel username="ytuser" adminToken="tok" platform="youtube" />
      </ToastProvider>
    );

    expect(await screen.findByText(/Google отклонил автоматизированный вход/i)).toBeInTheDocument();
    expect(screen.getAllByText(/signin\/rejected/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/Импорт сессии \(надёжный обход\)/i)).toBeInTheDocument();
    expect(screen.getByText(/google-studio-vnc-runbook/i)).toBeInTheDocument();
    expect(screen.getByText(/не обходит rejected/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Загрузить Playwright state/i })).toBeInTheDocument();
  });

  it("imports Playwright state and probes Studio connection", async () => {
    apiMock.browserStatus.mockResolvedValue({
      username: "ytuser",
      status: "running",
      awaiting_code: false,
      vnc_path: "api/accounts/ytuser/browser/vnc/ws",
      page_url: "https://accounts.google.com/v3/signin/rejected",
      account_username: "ytuser",
      account_login: "yt@mail.com",
      account_password: "x",
      account_notes: null,
    });
    apiMock.importCookiesFile.mockResolvedValue({
      format: "playwright_state",
      playwright_state_saved: true,
    });
    apiMock.testConnection.mockResolvedValue({
      overall_ok: true,
      studio_liveness_ok: true,
    });

    render(
      <ToastProvider>
        <InstagramBrowserPanel username="ytuser" adminToken="tok" platform="youtube" />
      </ToastProvider>
    );

    await screen.findByRole("button", { name: /Загрузить Playwright state/i });
    fireEvent.click(screen.getByRole("button", { name: /Загрузить Playwright state/i }));

    const input = document.getElementById("studio-state-file-ytuser") as HTMLInputElement;
    expect(input).toBeTruthy();
    const file = new File(['{"cookies":[]}'], "state.json", { type: "application/json" });
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => {
      expect(apiMock.importCookiesFile).toHaveBeenCalledWith("ytuser", file);
    });
    await waitFor(() => {
      expect(apiMock.testConnection).toHaveBeenCalledWith("ytuser", { probeStudio: true });
    });
  });

  it("copy and paste account credentials", async () => {
    const { copyTextToClipboard } = await import("../DiagnosticLogPanel");
    const copySpy = vi.mocked(copyTextToClipboard);
    copySpy.mockResolvedValue(true);
    apiMock.browserPaste.mockResolvedValue({
      username: "alice",
      status: "running",
      awaiting_code: false,
      vnc_path: "api/accounts/alice/browser/vnc/ws",
      account_username: "alice",
      account_login: "alice@mail.com",
      account_password: "secret123",
    });

    render(
      <ToastProvider>
        <InstagramBrowserPanel username="alice" adminToken="tok" />
      </ToastProvider>
    );

    await screen.findByRole("button", { name: /Копировать логин/i });
    fireEvent.click(screen.getByRole("button", { name: /Копировать пароль/i }));
    await waitFor(() => {
      expect(copySpy).toHaveBeenCalledWith("secret123");
    });

    fireEvent.click(screen.getByRole("button", { name: /Вставить логин в VNC/i }));
    await waitFor(() => {
      expect(apiMock.browserPaste).toHaveBeenCalledWith("alice", "alice@mail.com");
    });
  });

  it("confirms YouTube Google autofill", async () => {
    apiMock.browserStatus.mockResolvedValue({
      username: "ytuser",
      status: "running",
      awaiting_code: false,
      vnc_path: "api/accounts/ytuser/browser/vnc/ws",
      account_username: "ytuser",
      account_login: "yt@mail.com",
      account_password: "secret",
      account_notes: null,
    });
    apiMock.browserOpenInstagram.mockResolvedValue({
      username: "ytuser",
      status: "running",
      awaiting_code: false,
      vnc_path: "api/accounts/ytuser/browser/vnc/ws",
    });

    render(
      <ToastProvider>
        <InstagramBrowserPanel username="ytuser" adminToken="tok" platform="youtube" />
      </ToastProvider>
    );

    await screen.findByTitle(/Браузер VNC YouTube · @ytuser/i);
    const autofillBtn = primaryToolbarButton(/Google автозаполнение/i);
    expect(autofillBtn).not.toBeDisabled();
    fireEvent.click(autofillBtn);
    expect(
      await screen.findByText(/Google может отклонить автоматизированный ввод/i)
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Всё равно автозаполнить/i }));
    await waitFor(() => {
      expect(apiMock.browserOpenInstagram).toHaveBeenCalledWith("ytuser", {
        autofill: true,
        target: "auto",
      });
    });
  });

  it("shows Studio actions for YouTube, not Instagram quick nav", async () => {
    render(
      <ToastProvider>
        <InstagramBrowserPanel username="ytuser" adminToken="tok" platform="youtube" />
      </ToastProvider>
    );

    expect(primaryToolbarButton(/Открыть Studio/i)).toBeInTheDocument();
    expect(primaryToolbarButton(/Google автозаполнение/i)).toBeInTheDocument();
    expect(screen.queryByText(/Быстрый переход в Instagram/i)).not.toBeInTheDocument();
    expect(
      await screen.findByTitle(/Браузер VNC YouTube · @ytuser/i)
    ).toBeInTheDocument();
  });

  it("hides Instagram proxy reachability lines for YouTube and shows neutral note", async () => {
    apiMock.browserStatus.mockResolvedValue({
      username: "ytuser",
      status: "running",
      awaiting_code: false,
      vnc_path: "api/accounts/ytuser/browser/vnc/ws",
      page_url: "https://studio.youtube.com/",
      proxy_label: "p1",
      proxy_ip: "1.1.1.1",
      proxy_instagram_reachable: true,
      proxy_instagram_login_reachable: false,
      proxy_instagram_login_http_status: 403,
      account_username: "ytuser",
      account_login: "yt@mail.com",
      account_password: "x",
      account_notes: null,
    });

    render(
      <ToastProvider>
        <InstagramBrowserPanel username="ytuser" adminToken="tok" platform="youtube" />
      </ToastProvider>
    );

    expect(
      await screen.findByText(/Проверки Instagram API \/ страницы входа относятся только/i)
    ).toBeInTheDocument();
    expect(screen.queryByText(/Instagram API:/i)).not.toBeInTheDocument();
  });

  it("shows TikTok autofill label without Google in button text", async () => {
    render(
      <ToastProvider>
        <InstagramBrowserPanel username="ttuser" adminToken="tok" platform="tiktok" />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(primaryToolbarButton(/Открыть Studio/i)).toBeInTheDocument();
    });
    expect(screen.queryByRole("button", { name: /Google автозаполнение/i })).not.toBeInTheDocument();
    expect(primaryToolbarButton(/Автозаполнение логина/i)).toBeInTheDocument();
  });

  it("calls browserStatus again when clicking refresh", async () => {
    const startCalls = apiMock.browserStatus.mock.calls.length;
    render(
      <ToastProvider>
        <InstagramBrowserPanel username="alice" adminToken="tok" />
      </ToastProvider>
    );

    const btn = await screen.findByRole("button", { name: /Обновить статус/i });
    fireEvent.click(btn);

    await waitFor(() => {
      expect(apiMock.browserStatus.mock.calls.length).toBeGreaterThan(startCalls + 1);
    });
  });

  it("shows status row with badge and hint when session is running", async () => {
    render(
      <ToastProvider>
        <InstagramBrowserPanel username="alice" adminToken="tok" />
      </ToastProvider>
    );

    expect(await screen.findByText("Сейчас")).toBeInTheDocument();
    expect(screen.getByText("В работе")).toBeInTheDocument();
    expect(
      screen.getByText(/Можно переходить по разделам и сохранять сессию/i)
    ).toBeInTheDocument();
  });

  it("shows VNC connecting overlay while status is starting", async () => {
    apiMock.browserStatus.mockResolvedValueOnce({
      username: "alice",
      status: "starting",
      awaiting_code: false,
      vnc_path: "api/accounts/alice/browser/vnc/ws",
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

    expect(await screen.findByLabelText(/Подключение к VNC/i)).toBeInTheDocument();
  });

  it("re-enables save cookies after page_url changes post successful save", async () => {
    let pageUrl = "https://www.instagram.com/a";
    apiMock.browserStatus.mockImplementation(async () => ({
      username: "alice",
      status: "running",
      awaiting_code: false,
      vnc_path: "api/accounts/alice/browser/vnc/ws",
      page_url: pageUrl,
      account_username: "alice",
      account_login: "alice@mail.com",
      account_password: "secret123",
      account_notes: null,
    }));
    apiMock.browserSave.mockResolvedValueOnce({
      username: "alice",
      status: "saved",
      awaiting_code: false,
      vnc_path: "api/accounts/alice/browser/vnc/ws",
      session_imported: true,
      session_id_saved: true,
      overall_ok: true,
      connection_test: { overall_ok: true, logs: [] },
    });

    render(
      <ToastProvider>
        <InstagramBrowserPanel username="alice" adminToken="tok" />
      </ToastProvider>
    );

    const saveBtn = await screen.findByRole("button", { name: /Сохранить сессию и куки/i });
    await waitFor(() => expect(saveBtn).not.toBeDisabled());
    fireEvent.click(saveBtn);

    await waitFor(() => expect(apiMock.browserSave).toHaveBeenCalled());
    await waitFor(() => expect(saveBtn).toBeDisabled());

    pageUrl = "https://www.instagram.com/b";
    fireEvent.click(screen.getByRole("button", { name: /Обновить статус/i }));

    await waitFor(() => expect(saveBtn).not.toBeDisabled());
  });
});
