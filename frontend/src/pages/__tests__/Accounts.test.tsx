import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../../context/ToastContext";
import type { AccountOut, ProxyOut } from "../../api/types";
import { byLabel } from "../../test/utils";
import { Accounts } from "../Accounts";

const apiMock = vi.hoisted(() => ({
  accounts: {
    list: vi.fn(),
    create: vi.fn(),
    updateProxy: vi.fn(),
    updateSession: vi.fn(),
    getSession: vi.fn(),
    testConnection: vi.fn(),
    firstLogin: vi.fn(),
    mintMobileSession: vi.fn(),
    exportCookies: vi.fn(),
    exportPlaywrightState: vi.fn(),
    exportDeviceFingerprint: vi.fn(),
    importCookiesFile: vi.fn(),
    pause: vi.fn(),
    resume: vi.fn(),
  },
  proxies: {
    list: vi.fn(),
    create: vi.fn(),
    check: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
  },
  diagnostics: {
    list: vi.fn(),
    get: vi.fn(),
  },
}));

vi.mock("../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../api/client")>(
    "../../api/client"
  );
  return {
    ...actual,
    api: apiMock,
  };
});

vi.mock("../../context/AuthContext", () => ({
  useAuth: () => ({
    state: { state: "open" as const },
    login: vi.fn(),
    logout: vi.fn(),
    authRequired: false,
  }),
  AuthProvider: ({ children }: { children: React.ReactNode }) => children,
}));

const proxy: ProxyOut = {
  id: 1,
  label: "res-de-1",
  url: "http://h",
  country: "DE",
  timezone: "Europe/Berlin",
  is_healthy: true,
  last_known_ip: "203.0.113.1",
  last_geo_country: "DE",
  last_checked_at: null,
  notes: null,
  accounts_count: 1,
};

const secondProxy: ProxyOut = {
  ...proxy,
  id: 2,
  label: "res-us-1",
  url: "http://us",
  country: "US",
  timezone: "America/New_York",
  accounts_count: 0,
};

const account: AccountOut = {
  id: 10,
  username: "alice",
  status: "active",
  proxy_id: 1,
  proxy_label: "res-de-1",
  proxy_country: "DE",
  proxy_geo_country: "DE",
  proxy_is_healthy: true,
  proxy_last_ip: "203.0.113.1",
  timezone: "UTC",
  daily_post_cap: 3,
  min_gap_hours: 4,
  active_hour_start: 10,
  active_hour_end: 22,
  last_publish_at: null,
  last_idle_warmup_at: null,
  last_session_rotation_at: null,
  cooldown_until: null,
  caption_profile: null,
  has_totp: false,
  has_session_id: false,
  session_file_exists: true,
  session_file_updated_at: "2026-06-01T12:00:00Z",
  session_source: "session_file",
  posts_today: 1,
  failures_today: 0,
};

beforeEach(() => {
  Object.values(apiMock.accounts).forEach((fn) => fn.mockReset());
  Object.values(apiMock.proxies).forEach((fn) => fn.mockReset());
  Object.values(apiMock.diagnostics).forEach((fn) => fn.mockReset());
  apiMock.accounts.list.mockResolvedValue([account]);
  apiMock.proxies.list.mockResolvedValue([proxy]);
  apiMock.diagnostics.list.mockResolvedValue([]);
});

function renderAccounts() {
  return render(
    <ToastProvider>
      <Accounts />
    </ToastProvider>
  );
}

describe("Accounts page", () => {
  it("renders proxies and accounts tables after load", async () => {
    renderAccounts();
    await screen.findByText("@alice");
    const matches = screen.getAllByText("res-de-1");
    expect(matches.length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("203.0.113.1")).toBeInTheDocument();
    const instagramLink = screen.getByRole("link", { name: /профиль/i });
    expect(instagramLink).toHaveAttribute(
      "href",
      "https://www.instagram.com/alice/"
    );
    expect(instagramLink).toHaveAttribute("target", "_blank");
  });

  it("can reassign a proxy to an existing account", async () => {
    const updatedAccount = {
      ...account,
      proxy_id: secondProxy.id,
      proxy_label: secondProxy.label,
    };
    apiMock.accounts.list
      .mockResolvedValueOnce([account])
      .mockResolvedValueOnce([updatedAccount]);
    apiMock.proxies.list
      .mockResolvedValueOnce([proxy, secondProxy])
      .mockResolvedValueOnce([
        { ...proxy, accounts_count: 0 },
        { ...secondProxy, accounts_count: 1 },
      ]);
    apiMock.accounts.updateProxy.mockResolvedValue(updatedAccount);

    renderAccounts();
    await screen.findByText("@alice");

    fireEvent.click(
      screen.getByRole("button", { name: /сменить прокси для alice/i })
    );
    const heading = await screen.findByRole("heading", {
      name: /сменить прокси · @alice/i,
    });
    const modal = heading.closest("div.card") as HTMLElement;
    fireEvent.change(within(modal).getByRole("combobox"), {
      target: { value: secondProxy.label },
    });
    fireEvent.click(screen.getByRole("button", { name: /сохранить прокси/i }));

    await waitFor(() =>
      expect(apiMock.accounts.updateProxy).toHaveBeenCalledWith("alice", {
        proxy_label: secondProxy.label,
      })
    );
    await waitFor(() => {
      const accountsTable = screen.getAllByRole("table")[1];
      expect(within(accountsTable).getByText(secondProxy.label)).toBeInTheDocument();
    });
  });

  it("shows disabled account proxy assignment when no proxies exist", async () => {
    apiMock.proxies.list.mockResolvedValue([]);
    apiMock.accounts.list.mockResolvedValue([{ ...account, proxy_id: null, proxy_label: null }]);
    renderAccounts();
    await screen.findByText("@alice");

    fireEvent.click(
      screen.getByRole("button", { name: /сменить прокси для alice/i })
    );
    const heading = await screen.findByRole("heading", {
      name: /сменить прокси · @alice/i,
    });
    const modal = heading.closest("div.card") as HTMLElement;

    expect(within(modal).getByText(/нет прокси\. сначала добавьте/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /сохранить прокси/i })).toBeDisabled();
    expect(apiMock.accounts.updateProxy).not.toHaveBeenCalled();
  });

  it("can import a browser session for an existing account", async () => {
    const sessionId = "a".repeat(40);
    const updatedAccount = { ...account, has_session_id: true };
    apiMock.accounts.list
      .mockResolvedValueOnce([account])
      .mockResolvedValueOnce([updatedAccount])
      .mockResolvedValue([updatedAccount]);
    apiMock.accounts.updateSession.mockResolvedValue(updatedAccount);
    apiMock.accounts.testConnection.mockResolvedValue({
      username: "alice",
      proxy_assigned: true,
      proxy_label: "res-de-1",
      proxy_health: {
        ok: true,
        ip: "1.2.3.4",
        geo_country: "DE",
        instagram_reachable: true,
        geo_mismatch: false,
      },
      session_storage: {
        has_session_id: true,
        session_file_exists: false,
        device_file_exists: true,
        session_source: "database",
      },
      instagram_auth: {
        ok: true,
        method: "sessionid",
        ig_username: "alice",
        challenge: false,
      },
      overall_ok: true,
      checked_at: "2026-06-29T10:00:00Z",
      run_id: 11,
      logs: [],
    });

    renderAccounts();
    await screen.findByText("@alice");

    fireEvent.click(screen.getByRole("button", { name: /сессия для alice/i }));
    const heading = await screen.findByRole("heading", {
      name: /сессия · @alice/i,
    });
    const modal = heading.closest("div.card") as HTMLElement;
    fireEvent.change(byLabel(/cookie sessionid/i, modal), {
      target: { value: sessionId },
    });
    fireEvent.click(screen.getByRole("button", { name: /сохранить сессию/i }));

    await waitFor(() =>
      expect(apiMock.accounts.updateSession).toHaveBeenCalledWith("alice", {
        session_id: sessionId,
      })
    );
    expect(apiMock.accounts.importCookiesFile).not.toHaveBeenCalled();
    expect(apiMock.accounts.testConnection).not.toHaveBeenCalled();
    // Modal stays open after save.
    expect(screen.getByRole("heading", { name: /сессия · @alice/i })).toBeInTheDocument();
  });

  it("decodes URL-encoded sessionid before save", async () => {
    const encoded =
      "38945170646%3AG5p9NNhoGGVDGE%3A20%3AAYhWdcBsbiU0mVgtsM9jvb0aRWnNqazSIs__yXPUMw";
    const decoded =
      "38945170646:G5p9NNhoGGVDGE:20:AYhWdcBsbiU0mVgtsM9jvb0aRWnNqazSIs__yXPUMw";
    apiMock.accounts.list.mockResolvedValue([account]);
    apiMock.accounts.updateSession.mockResolvedValue({ ...account, has_session_id: true });
    apiMock.accounts.testConnection.mockResolvedValue({
      username: "alice",
      proxy_assigned: true,
      proxy_label: "res-de-1",
      proxy_health: {
        ok: true,
        ip: "1.2.3.4",
        geo_country: "DE",
        instagram_reachable: true,
        geo_mismatch: false,
      },
      session_storage: {
        has_session_id: true,
        session_file_exists: false,
        device_file_exists: true,
        session_source: "database",
      },
      instagram_auth: {
        ok: false,
        method: "sessionid",
        error: "session_id недействителен или истёк",
        error_code: "session_expired",
        challenge: false,
      },
      overall_ok: false,
      checked_at: "2026-06-29T10:00:00Z",
      run_id: 12,
      logs: [],
    });

    renderAccounts();
    await screen.findByText("@alice");
    fireEvent.click(screen.getByRole("button", { name: /сессия для alice/i }));
    const heading = await screen.findByRole("heading", { name: /сессия · @alice/i });
    const modal = heading.closest("div.card") as HTMLElement;
    fireEvent.change(byLabel(/cookie sessionid/i, modal), {
      target: { value: encoded },
    });
    fireEvent.click(screen.getByRole("button", { name: /сохранить сессию/i }));

    await waitFor(() =>
      expect(apiMock.accounts.updateSession).toHaveBeenCalledWith("alice", {
        session_id: decoded,
      })
    );
    expect(apiMock.accounts.testConnection).not.toHaveBeenCalled();
  });

  it("accepts .txt cookie files in session import", async () => {
    renderAccounts();
    await screen.findByText("@alice");
    fireEvent.click(screen.getByRole("button", { name: /сессия для alice/i }));
    const heading = await screen.findByRole("heading", { name: /сессия · @alice/i });
    const modal = heading.closest("div.card") as HTMLElement;
    const input = within(modal).getByLabelText(/импорт cookies из файла/i);
    expect(input).toHaveAttribute("accept", expect.stringContaining(".txt"));
  });

  it("can export session from the session modal", async () => {
    const sessionId = "b".repeat(40);
    apiMock.accounts.getSession.mockResolvedValue({
      session_id: sessionId,
      source: "database",
      session_file_exists: true,
    });

    renderAccounts();
    await screen.findByText("@alice");
    fireEvent.click(screen.getByRole("button", { name: /сессия для alice/i }));
    await screen.findByRole("heading", { name: /сессия · @alice/i });
    fireEvent.click(screen.getByRole("button", { name: /^экспорт$/i }));

    await waitFor(() =>
      expect(apiMock.accounts.getSession).toHaveBeenCalledWith("alice")
    );
    await waitFor(() =>
      expect(screen.getByDisplayValue(sessionId)).toBeInTheDocument()
    );
  });

  it("shows Dolphin export buttons on export tab", async () => {
    apiMock.accounts.getSession.mockResolvedValue({
      session_id: "c".repeat(40),
      source: "database",
      session_file_exists: true,
    });

    renderAccounts();
    await screen.findByText("@alice");
    fireEvent.click(screen.getByRole("button", { name: /сессия для alice/i }));
    await screen.findByRole("heading", { name: /сессия · @alice/i });
    fireEvent.click(screen.getByRole("button", { name: /^экспорт$/i }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /скачать cookies \(dolphin\)/i })).toBeInTheDocument()
    );
    expect(
      screen.getByRole("button", { name: /скачать playwright state\.json/i })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /скачать device fingerprint/i })
    ).toBeInTheDocument();
  });

  it("can import cookies from file in session modal", async () => {
    const updatedAccount = { ...account, has_session_id: true };
    apiMock.accounts.list
      .mockResolvedValueOnce([account])
      .mockResolvedValueOnce([updatedAccount]);
    const importedSid = "d".repeat(40);
    apiMock.accounts.importCookiesFile.mockResolvedValue({
      format: "dolphin",
      session_id: importedSid,
      session_id_imported: true,
      playwright_state_saved: true,
      session_file_cleared: true,
    });

    renderAccounts();
    await screen.findByText("@alice");
    fireEvent.click(screen.getByRole("button", { name: /сессия для alice/i }));
    const heading = await screen.findByRole("heading", { name: /сессия · @alice/i });
    const modal = heading.closest("div.card") as HTMLElement;

    const file = new File(
      ['[{"name":"sessionid","value":"' + importedSid + '"}]'],
      "cookies.json",
      { type: "application/json" }
    );
    const input = within(modal).getByLabelText(/импорт cookies из файла/i);
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /импортировать файл/i })).toBeInTheDocument()
    );
    fireEvent.click(screen.getByRole("button", { name: /импортировать файл/i }));

    await waitFor(() =>
      expect(apiMock.accounts.importCookiesFile).toHaveBeenCalledWith("alice", file)
    );
    await waitFor(() =>
      expect(within(modal).getByLabelText(/sessionid/i)).toHaveValue(importedSid)
    );
    expect(apiMock.accounts.updateSession).not.toHaveBeenCalled();
    expect(apiMock.accounts.testConnection).not.toHaveBeenCalled();
  });

  it("shows error when saving session with neither sessionid nor file", async () => {
    renderAccounts();
    await screen.findByText("@alice");
    fireEvent.click(screen.getByRole("button", { name: /сессия для alice/i }));
    await screen.findByRole("heading", { name: /сессия · @alice/i });
    fireEvent.click(screen.getByRole("button", { name: /сохранить сессию/i }));

    await screen.findByText(/вставьте sessionid.*или выберите json\/txt cookies/i);
    expect(apiMock.accounts.updateSession).not.toHaveBeenCalled();
    expect(apiMock.accounts.importCookiesFile).not.toHaveBeenCalled();
  });

  it("can test proxy from change-proxy modal and shows instagram reachability", async () => {
    apiMock.proxies.list.mockResolvedValue([proxy, secondProxy]);
    apiMock.proxies.check.mockResolvedValue({
      ...secondProxy,
      is_healthy: true,
      last_known_ip: "198.51.100.2",
      instagram_reachable: true,
      geo_mismatch_warning: false,
    });

    renderAccounts();
    await screen.findByText("@alice");
    fireEvent.click(
      screen.getByRole("button", { name: /сменить прокси для alice/i })
    );
    const heading = await screen.findByRole("heading", {
      name: /сменить прокси · @alice/i,
    });
    const modal = heading.closest("div.card") as HTMLElement;
    fireEvent.change(within(modal).getByRole("combobox"), {
      target: { value: secondProxy.label },
    });
    fireEvent.click(
      within(modal).getByRole("button", { name: /проверить выбранный прокси/i })
    );

    await waitFor(() =>
      expect(apiMock.proxies.check).toHaveBeenCalledWith(secondProxy.label)
    );
    await waitFor(() =>
      expect(within(modal).getByText("198.51.100.2")).toBeInTheDocument()
    );
    expect(within(modal).getByText(/доступен/i)).toBeInTheDocument();
  });

  it("opens connection modal and runs cookies-only connection check", async () => {
    apiMock.accounts.testConnection.mockResolvedValue({
      username: "alice",
      proxy_assigned: true,
      proxy_label: "res-de-1",
      proxy_health: {
        ok: true,
        ip: "203.0.113.1",
        geo_country: "DE",
        instagram_reachable: true,
        geo_mismatch: false,
      },
      session_storage: {
        has_session_id: false,
        session_file_exists: true,
        device_file_exists: true,
        session_source: "session_file",
      },
      instagram_auth: {
        ok: true,
        method: "session_file",
        ig_username: null,
        challenge: false,
      },
      overall_ok: true,
      checked_at: "2026-06-29T10:00:00Z",
      run_id: 1,
      logs: [{ ts: "2026-06-29T10:00:00Z", level: "info", step: "proxy", message: "ok" }],
    });

    renderAccounts();
    await screen.findByText("@alice");
    fireEvent.click(
      screen.getByRole("button", { name: /^подключение для alice$/i })
    );
    const heading = await screen.findByRole("heading", {
      name: /подключение · @alice/i,
    });
    const modal = heading.closest("div.card") as HTMLElement;
    expect(within(modal).getByText(/прокси назначен/i)).toBeInTheDocument();
    fireEvent.click(within(modal).getByRole("button", { name: /запустить проверку/i }));

    await waitFor(() =>
      expect(apiMock.accounts.testConnection).toHaveBeenCalledWith("alice", {
        probeMobile: false,
      })
    );
    await waitFor(() =>
      expect(within(modal).getByText(/4\. cookies установлены/i)).toBeInTheDocument()
    );
    expect(within(modal).getAllByText(/cookies установлены/i).length).toBeGreaterThanOrEqual(1);
  });

  it("runs mobile API probe from connection modal", async () => {
    apiMock.accounts.testConnection.mockResolvedValue({
      username: "alice",
      proxy_assigned: true,
      proxy_label: "res-de-1",
      proxy_health: {
        ok: true,
        ip: "203.0.113.1",
        geo_country: "DE",
        instagram_reachable: true,
        geo_mismatch: false,
      },
      session_storage: {
        has_session_id: true,
        session_file_exists: false,
        device_file_exists: true,
        session_source: "database",
      },
      instagram_auth: {
        ok: true,
        method: "sessionid",
        ig_username: "alice",
        challenge: false,
      },
      overall_ok: true,
      checked_at: "2026-06-29T10:00:00Z",
      run_id: 2,
      logs: [],
    });

    renderAccounts();
    await screen.findByText("@alice");
    fireEvent.click(
      screen.getByRole("button", { name: /^подключение для alice$/i })
    );
    const heading = await screen.findByRole("heading", {
      name: /подключение · @alice/i,
    });
    const modal = heading.closest("div.card") as HTMLElement;
    fireEvent.click(within(modal).getByRole("button", { name: /проверить mobile api/i }));

    await waitFor(() =>
      expect(apiMock.accounts.testConnection).toHaveBeenCalledWith("alice", {
        probeMobile: true,
      })
    );
    await waitFor(() =>
      expect(within(modal).getByText(/готов к автопостингу/i)).toBeInTheDocument()
    );
    expect(within(modal).getByText(/4\. сессия действительна/i)).toBeInTheDocument();
  });

  it("shows connection failure after test completes", async () => {
    apiMock.diagnostics.list.mockResolvedValue([]);
    apiMock.accounts.testConnection.mockResolvedValue({
      username: "alice",
      proxy_assigned: true,
      proxy_label: "res-de-1",
      proxy_health: {
        ok: true,
        ip: "203.0.113.1",
        geo_country: "DE",
        instagram_reachable: true,
        instagram_login_reachable: true,
        geo_mismatch: false,
      },
      session_storage: {
        has_session_id: true,
        session_file_exists: false,
        device_file_exists: true,
        session_source: "database",
      },
      instagram_auth: {
        ok: false,
        method: "sessionid",
        ig_username: null,
        error: "session_id недействителен или истёк",
        error_code: "session_expired",
        challenge: false,
      },
      overall_ok: false,
      checked_at: "2026-06-29T10:00:00Z",
      run_id: 35,
      logs: [
        {
          ts: "2026-06-29T10:00:00Z",
          level: "error",
          step: "session_probe",
          message: "session_id недействителен или истёк",
        },
      ],
    });

    renderAccounts();
    await screen.findByText("@alice");
    fireEvent.click(
      screen.getByRole("button", { name: /^подключение для alice$/i })
    );
    const heading = await screen.findByRole("heading", {
      name: /подключение · @alice/i,
    });
    const modal = heading.closest("div.card") as HTMLElement;
    fireEvent.click(within(modal).getByRole("button", { name: /проверить mobile api/i }));

    await waitFor(() =>
      expect(within(modal).getByText(/не готов к автопостингу/i)).toBeInTheDocument()
    );
    expect(within(modal).getByText(/4\. сессия недействительна/i)).toBeInTheDocument();
    expect(
      within(modal).getAllByText(/session_id недействителен или истёк/i).length
    ).toBeGreaterThanOrEqual(1);
    expect(within(modal).getByText(/mobile api отклонил sessionid/i)).toBeInTheDocument();
    expect(
      within(modal).getByText(/web-cookie из dolphin часто отклоняется/i)
    ).toBeInTheDocument();
    expect(
      within(modal).getByRole("button", { name: /подготовить к автопостингу/i })
    ).toBeInTheDocument();
    expect(within(modal).queryByText(/выполняется проверка/i)).not.toBeInTheDocument();
  });

  it("mints mobile session from connection modal when session expired", async () => {
    apiMock.diagnostics.list.mockResolvedValue([]);
    apiMock.accounts.testConnection
      .mockResolvedValueOnce({
        username: "alice",
        proxy_assigned: true,
        proxy_label: "res-de-1",
        proxy_health: {
          ok: true,
          ip: "203.0.113.1",
          geo_country: "DE",
          instagram_reachable: true,
          instagram_login_reachable: true,
          geo_mismatch: false,
        },
        session_storage: {
          has_session_id: true,
          session_file_exists: false,
          device_file_exists: true,
          session_source: "database",
        },
        instagram_auth: {
          ok: false,
          method: "sessionid",
          ig_username: null,
          error: "session_id недействителен или истёк",
          error_code: "session_expired",
          challenge: false,
        },
        overall_ok: false,
        checked_at: "2026-06-29T10:00:00Z",
        run_id: 35,
        logs: [],
      })
      .mockResolvedValueOnce({
        username: "alice",
        proxy_assigned: true,
        proxy_label: "res-de-1",
        proxy_health: {
          ok: true,
          ip: "203.0.113.1",
          geo_country: "DE",
          instagram_reachable: true,
          instagram_login_reachable: true,
          geo_mismatch: false,
        },
        session_storage: {
          has_session_id: true,
          session_file_exists: true,
          device_file_exists: true,
          session_source: "database",
        },
        instagram_auth: {
          ok: true,
          method: "sessionid",
          ig_username: "alice",
          challenge: false,
        },
        overall_ok: true,
        checked_at: "2026-06-29T10:05:00Z",
        run_id: 36,
        logs: [],
      });
    apiMock.accounts.mintMobileSession.mockResolvedValue({
      run_id: 99,
      ok: true,
      challenge: false,
      session_id: "m".repeat(40),
      logs: [],
    });

    renderAccounts();
    await screen.findByText("@alice");
    fireEvent.click(
      screen.getByRole("button", { name: /^подключение для alice$/i })
    );
    const heading = await screen.findByRole("heading", {
      name: /подключение · @alice/i,
    });
    const modal = heading.closest("div.card") as HTMLElement;
    fireEvent.click(within(modal).getByRole("button", { name: /проверить mobile api/i }));

    await waitFor(() =>
      expect(
        within(modal).getByRole("button", { name: /подготовить к автопостингу/i })
      ).toBeInTheDocument()
    );
    fireEvent.click(
      within(modal).getByRole("button", { name: /подготовить к автопостингу/i })
    );

    await waitFor(() =>
      expect(apiMock.accounts.mintMobileSession).toHaveBeenCalledWith("alice")
    );
    await waitFor(() =>
      expect(within(modal).getByText(/готов к автопостингу/i)).toBeInTheDocument()
    );
    expect(apiMock.accounts.testConnection).toHaveBeenCalledWith("alice", {
      probeMobile: true,
    });
  });

  it("opens session setup modal when connection test reports missing session", async () => {
    apiMock.accounts.testConnection.mockResolvedValue({
      username: "alice",
      proxy_assigned: true,
      proxy_label: "res-de-1",
      proxy_health: {
        ok: true,
        ip: "203.0.113.1",
        geo_country: "DE",
        instagram_reachable: true,
        geo_mismatch: false,
      },
      session_storage: {
        has_session_id: false,
        session_file_exists: false,
        device_file_exists: true,
        session_source: "none",
      },
      instagram_auth: {
        ok: false,
        method: "none",
        error: "Нет session_id в БД",
        error_code: "session_missing",
        challenge: false,
      },
      overall_ok: false,
      checked_at: "2026-06-29T10:00:00Z",
      run_id: 2,
      logs: [],
    });

    renderAccounts();
    await screen.findByText("@alice");
    fireEvent.click(
      screen.getByRole("button", { name: /^подключение для alice$/i })
    );
    const connHeading = await screen.findByRole("heading", {
      name: /подключение · @alice/i,
    });
    const connModal = connHeading.closest("div.card") as HTMLElement;
    fireEvent.click(within(connModal).getByRole("button", { name: /запустить проверку/i }));

    await waitFor(() =>
      expect(apiMock.accounts.testConnection).toHaveBeenCalledWith("alice", {
        probeMobile: false,
      })
    );
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: /настройка сессии · @alice/i })
      ).toBeInTheDocument()
    );
  });

  it("shows cookies badge when session file exists", async () => {
    renderAccounts();
    await screen.findByText("@alice");
    expect(screen.getByText("Cookies")).toBeInTheDocument();
  });

  it("can quick-test connection from account proxy cell", async () => {
    renderAccounts();
    await screen.findByText("@alice");
    fireEvent.click(
      screen.getByRole("button", { name: /проверка подключения для alice/i })
    );
    await screen.findByRole("heading", { name: /подключение · @alice/i });
  });

  it("opens the Add account modal and submits a new account", async () => {
    apiMock.accounts.create.mockResolvedValue({
      ...account,
      id: 11,
      username: "bob",
    });
    apiMock.accounts.list.mockResolvedValue([
      account,
      { ...account, id: 11, username: "bob" },
    ]);
    renderAccounts();
    await screen.findByText("@alice");

    fireEvent.click(screen.getByRole("button", { name: /добавить аккаунт/i }));
    const heading = await screen.findByRole("heading", { name: /добавить аккаунт/i });
    const modal = heading.closest("div.card") as HTMLElement;
    expect(modal).toBeInTheDocument();

    fireEvent.change(byLabel(/имя пользователя/i, modal), { target: { value: "bob" } });
    fireEvent.change(byLabel(/^пароль$/i, modal), { target: { value: "secret" } });
    fireEvent.click(screen.getByRole("button", { name: /сохранить аккаунт/i }));

    await waitFor(() =>
      expect(apiMock.accounts.create).toHaveBeenCalledWith(
        expect.objectContaining({
          username: "bob",
          password: "secret",
          proxy_label: "res-de-1",
        })
      )
    );
  });

  it("shows validation toast when required fields are empty", async () => {
    renderAccounts();
    await screen.findByText("@alice");
    fireEvent.click(screen.getByRole("button", { name: /добавить аккаунт/i }));
    await screen.findByRole("heading", { name: /добавить аккаунт/i });
    fireEvent.click(screen.getByRole("button", { name: /сохранить аккаунт/i }));
    await screen.findByText(/заполните имя пользователя, пароль и прокси/i);
    expect(apiMock.accounts.create).not.toHaveBeenCalled();
  });

  it("pauses an active account", async () => {
    apiMock.accounts.pause.mockResolvedValue({ ...account, status: "paused" });
    renderAccounts();
    await screen.findByText("@alice");

    const accountsTable = screen.getAllByRole("table")[1];
    const pauseBtn = within(accountsTable).getByRole("button", { name: /^пауза$/i });
    fireEvent.click(pauseBtn);

    await waitFor(() =>
      expect(apiMock.accounts.pause).toHaveBeenCalledWith("alice")
    );
  });

  it("resumes a paused account", async () => {
    apiMock.accounts.list.mockResolvedValue([{ ...account, status: "paused" }]);
    apiMock.accounts.resume.mockResolvedValue({ ...account, status: "active" });
    renderAccounts();
    await screen.findByText("@alice");
    const accountsTable = screen.getAllByRole("table")[1];
    fireEvent.click(within(accountsTable).getByRole("button", { name: /возобновить/i }));
    await waitFor(() =>
      expect(apiMock.accounts.resume).toHaveBeenCalledWith("alice")
    );
  });

  it("can add a new proxy via the modal", async () => {
    apiMock.proxies.create.mockResolvedValue(proxy);
    renderAccounts();
    await screen.findByText("@alice");

    fireEvent.click(screen.getByRole("button", { name: /добавить прокси/i }));
    const heading = await screen.findByRole("heading", { name: /добавить прокси/i });
    const modal = heading.closest("div.card") as HTMLElement;

    fireEvent.change(byLabel(/^метка$/i, modal), { target: { value: "res-eu-1" } });
    fireEvent.change(byLabel(/^url$/i, modal), {
      target: { value: "http://u:p@host:1" },
    });
    const skip = within(modal).getByRole("checkbox") as HTMLInputElement;
    fireEvent.click(skip);
    fireEvent.click(screen.getByRole("button", { name: /сохранить прокси/i }));

    await waitFor(() =>
      expect(apiMock.proxies.create).toHaveBeenCalledWith(
        expect.objectContaining({
          label: "res-eu-1",
          url: "http://u:p@host:1",
          skip_health_check: true,
        })
      )
    );
  });

  it("triggers health-check on proxy row", async () => {
    apiMock.proxies.check.mockResolvedValue({ ...proxy, is_healthy: false });
    renderAccounts();
    await screen.findByText("@alice");
    const proxiesTable = screen.getAllByRole("table")[0];
    fireEvent.click(
      within(proxiesTable).getByRole("button", {
        name: /проверка прокси res-de-1/i,
      })
    );
    await waitFor(() =>
      expect(apiMock.proxies.check).toHaveBeenCalledWith("res-de-1")
    );
  });

  it("opens Edit proxy modal and saves via API", async () => {
    apiMock.proxies.update.mockResolvedValue({ ...proxy, url: "http://new/url" });
    renderAccounts();
    await screen.findByText("@alice");
    fireEvent.click(
      screen.getByRole("button", { name: /изменить прокси res-de-1/i })
    );
    const heading = await screen.findByRole("heading", {
      name: /изменить прокси · res-de-1/i,
    });
    const modal = heading.closest("div.card") as HTMLElement;

    fireEvent.change(byLabel(/^url$/i, modal), {
      target: { value: "http://new/url" },
    });
    fireEvent.click(
      within(modal).getByRole("checkbox", { name: /пропустить проверку после сохранения/i })
    );
    fireEvent.click(screen.getByRole("button", { name: /сохранить изменения/i }));

    await waitFor(() =>
      expect(apiMock.proxies.update).toHaveBeenCalledWith(
        "res-de-1",
        expect.objectContaining({
          url: "http://new/url",
          skip_health_check: true,
        })
      )
    );
  });

  it("disables Delete proxy when accounts are attached", async () => {
    renderAccounts();
    await screen.findByText("@alice");
    const delBtn = screen.getByRole("button", { name: /удалить прокси res-de-1/i });
    expect(delBtn).toBeDisabled();
  });

  it("deletes unused proxy after confirm", async () => {
    const loose = { ...proxy, accounts_count: 0 };
    apiMock.proxies.list.mockResolvedValue([loose]);
    apiMock.accounts.list.mockResolvedValue([]);
    apiMock.proxies.remove.mockImplementation(async () => {
      apiMock.proxies.list.mockResolvedValue([]);
      return { ok: true };
    });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

    renderAccounts();
    await screen.findByText("Аккаунтов пока нет.");

    fireEvent.click(
      screen.getByRole("button", { name: /удалить прокси res-de-1/i })
    );
    await waitFor(() =>
      expect(apiMock.proxies.remove).toHaveBeenCalledWith("res-de-1")
    );
    confirmSpy.mockRestore();
  });

  it("renders cooldown badge and cooldown-until column for cooldown accounts", async () => {
    const cooldownIso = "2026-05-09T10:00:00Z";
    apiMock.accounts.list.mockResolvedValue([
      {
        ...account,
        status: "cooldown",
        cooldown_until: cooldownIso,
        caption_profile: "lifestyle",
      },
    ]);
    renderAccounts();
    await screen.findByText("@alice");
    const accountsTable = screen.getAllByRole("table")[1];
    expect(within(accountsTable).getByText("Пауза IG")).toBeInTheDocument();
    expect(within(accountsTable).getByText("lifestyle")).toBeInTheDocument();
    const expected = new Date(cooldownIso).toLocaleString();
    expect(within(accountsTable).getByText(expected)).toBeInTheDocument();
  });

  it("highlights geo mismatch in proxies table", async () => {
    apiMock.proxies.list.mockResolvedValue([
      { ...proxy, country: "DE", last_geo_country: "US" },
    ]);
    renderAccounts();
    await screen.findByText("@alice");
    const proxiesTable = screen.getAllByRole("table")[0];
    const cell = within(proxiesTable).getByText("US");
    expect(cell.className).toMatch(/amber/);
  });

  it("submits caption_profile and TOTP seed when filled", async () => {
    apiMock.accounts.create.mockResolvedValue({
      ...account,
      id: 11,
      username: "carol",
      caption_profile: "fitness",
      has_totp: true,
    });
    apiMock.accounts.list.mockResolvedValue([account]);
    renderAccounts();
    await screen.findByText("@alice");

    fireEvent.click(screen.getByRole("button", { name: /добавить аккаунт/i }));
    const heading = await screen.findByRole("heading", { name: /добавить аккаунт/i });
    const modal = heading.closest("div.card") as HTMLElement;

    fireEvent.change(byLabel(/имя пользователя/i, modal), { target: { value: "carol" } });
    fireEvent.change(byLabel(/^пароль$/i, modal), { target: { value: "pw" } });
    fireEvent.change(byLabel(/профиль подписей/i, modal), {
      target: { value: "fitness" },
    });
    fireEvent.change(byLabel(/totp seed/i, modal), {
      target: { value: "JBSWY3DPEHPK3PXP" },
    });
    fireEvent.click(screen.getByRole("button", { name: /сохранить аккаунт/i }));

    await waitFor(() =>
      expect(apiMock.accounts.create).toHaveBeenCalledWith(
        expect.objectContaining({
          username: "carol",
          caption_profile: "fitness",
          totp_seed: "JBSWY3DPEHPK3PXP",
        })
      )
    );
  });

  it("submits full add-account payload including optional fields", async () => {
    apiMock.accounts.create.mockResolvedValue({
      ...account,
      id: 12,
      username: "dave",
      caption_profile: "travel",
      has_totp: true,
    });
    renderAccounts();
    await screen.findByText("@alice");

    fireEvent.click(screen.getByRole("button", { name: /добавить аккаунт/i }));
    const heading = await screen.findByRole("heading", { name: /добавить аккаунт/i });
    const modal = heading.closest("div.card") as HTMLElement;

    fireEvent.change(byLabel(/имя пользователя/i, modal), { target: { value: "dave" } });
    fireEvent.change(byLabel(/^пароль$/i, modal), { target: { value: "pw-1" } });
    fireEvent.change(byLabel(/часовой пояс/i, modal), { target: { value: "Europe/Berlin" } });
    fireEvent.change(byLabel(/дневной лимит/i, modal), { target: { value: "4" } });
    fireEvent.change(byLabel(/мин\. пауза/i, modal), { target: { value: "5.5" } });
    fireEvent.change(byLabel(/начало активности/i, modal), { target: { value: "11" } });
    fireEvent.change(byLabel(/конец активности/i, modal), { target: { value: "23" } });
    fireEvent.change(byLabel(/профиль подписей/i, modal), { target: { value: "travel" } });
    fireEvent.change(byLabel(/totp seed/i, modal), { target: { value: "JBSWY3DPEHPK3PXP" } });
    fireEvent.change(byLabel(/резервный email/i, modal), { target: { value: "a@b.test" } });
    fireEvent.change(byLabel(/пароль email/i, modal), { target: { value: "mail-secret" } });
    fireEvent.click(screen.getByRole("button", { name: /сохранить аккаунт/i }));

    await waitFor(() =>
      expect(apiMock.accounts.create).toHaveBeenCalledWith({
        username: "dave",
        password: "pw-1",
        proxy_label: "res-de-1",
        timezone: "Europe/Berlin",
        daily_post_cap: 4,
        min_gap_hours: 5.5,
        active_hour_start: 11,
        active_hour_end: 23,
        caption_profile: "travel",
        totp_seed: "JBSWY3DPEHPK3PXP",
        email: "a@b.test",
        email_password: "mail-secret",
        login_identifier: null,
        account_line: null,
        backup_codes: null,
        notes: null,
      })
    );
  });

  it("normalizes empty optional add-account fields to null", async () => {
    apiMock.accounts.create.mockResolvedValue({ ...account, id: 13, username: "eva" });
    renderAccounts();
    await screen.findByText("@alice");

    fireEvent.click(screen.getByRole("button", { name: /добавить аккаунт/i }));
    const heading = await screen.findByRole("heading", { name: /добавить аккаунт/i });
    const modal = heading.closest("div.card") as HTMLElement;

    fireEvent.change(byLabel(/имя пользователя/i, modal), { target: { value: "eva" } });
    fireEvent.change(byLabel(/^пароль$/i, modal), { target: { value: "pw-2" } });
    fireEvent.change(byLabel(/totp seed/i, modal), { target: { value: "   " } });
    fireEvent.change(byLabel(/резервный email/i, modal), { target: { value: "   " } });
    fireEvent.change(byLabel(/пароль email/i, modal), { target: { value: "   " } });
    fireEvent.click(screen.getByRole("button", { name: /сохранить аккаунт/i }));

    await waitFor(() =>
      expect(apiMock.accounts.create).toHaveBeenCalledWith(
        expect.objectContaining({
          caption_profile: null,
          totp_seed: null,
          email: null,
          email_password: null,
        })
      )
    );
  });

  it("shows no-proxy state and blocks submit when proxies are missing", async () => {
    apiMock.proxies.list.mockResolvedValue([]);
    apiMock.accounts.list.mockResolvedValue([]);
    renderAccounts();
    await screen.findByText("Аккаунтов пока нет.");

    fireEvent.click(screen.getByRole("button", { name: /добавить аккаунт/i }));
    const heading = await screen.findByRole("heading", { name: /добавить аккаунт/i });
    const modal = heading.closest("div.card") as HTMLElement;
    expect(within(modal).getByText(/нет прокси\. сначала добавьте/i)).toBeInTheDocument();

    fireEvent.change(byLabel(/имя пользователя/i, modal), { target: { value: "neo" } });
    fireEvent.change(byLabel(/^пароль$/i, modal), { target: { value: "pw-3" } });
    fireEvent.click(screen.getByRole("button", { name: /сохранить аккаунт/i }));

    await screen.findByText(/заполните имя пользователя, пароль и прокси/i);
    expect(apiMock.accounts.create).not.toHaveBeenCalled();
  });

  it("resets busy state and shows toast when create fails", async () => {
    apiMock.accounts.create.mockRejectedValue(new Error("create failed"));
    renderAccounts();
    await screen.findByText("@alice");

    fireEvent.click(screen.getByRole("button", { name: /добавить аккаунт/i }));
    const heading = await screen.findByRole("heading", { name: /добавить аккаунт/i });
    const modal = heading.closest("div.card") as HTMLElement;

    fireEvent.change(byLabel(/имя пользователя/i, modal), { target: { value: "zoe" } });
    fireEvent.change(byLabel(/^пароль$/i, modal), { target: { value: "pw-4" } });
    fireEvent.click(screen.getByRole("button", { name: /сохранить аккаунт/i }));

    await screen.findByText("create failed");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /сохранить аккаунт/i })).toBeEnabled()
    );
  });

  it("resets add-account form values after successful save", async () => {
    apiMock.accounts.create.mockResolvedValue({ ...account, id: 14, username: "kate" });
    renderAccounts();
    await screen.findByText("@alice");

    fireEvent.click(screen.getByRole("button", { name: /добавить аккаунт/i }));
    let heading = await screen.findByRole("heading", { name: /добавить аккаунт/i });
    let modal = heading.closest("div.card") as HTMLElement;

    fireEvent.change(byLabel(/имя пользователя/i, modal), { target: { value: "kate" } });
    fireEvent.change(byLabel(/^пароль$/i, modal), { target: { value: "pw-5" } });
    fireEvent.change(byLabel(/часовой пояс/i, modal), { target: { value: "Europe/Warsaw" } });
    fireEvent.change(byLabel(/профиль подписей/i, modal), { target: { value: "food" } });
    fireEvent.click(screen.getByRole("button", { name: /сохранить аккаунт/i }));

    await screen.findByText(/аккаунт сохранён/i);
    fireEvent.click(screen.getByRole("button", { name: /добавить аккаунт/i }));
    heading = await screen.findByRole("heading", { name: /добавить аккаунт/i });
    modal = heading.closest("div.card") as HTMLElement;

    expect((byLabel(/имя пользователя/i, modal) as HTMLInputElement).value).toBe("");
    expect((byLabel(/^пароль$/i, modal) as HTMLInputElement).value).toBe("");
    expect((byLabel(/часовой пояс/i, modal) as HTMLInputElement).value).toBe("Europe/Berlin");
    expect((byLabel(/профиль подписей/i, modal) as HTMLSelectElement).value).toBe("");
  });
});
