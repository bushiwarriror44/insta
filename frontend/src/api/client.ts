import type {
  AccountConnectionTestOut,
  AccountIn,
  AccountNotesUpdate,
  AccountOut,
  AccountProxyUpdate,
  AccountSessionOut,
  AccountSessionUpdate,
  BrowserSaveOut,
  BrowserSessionOut,
  CookiesImportOut,
  DashboardSummary,
  DiagnosticRunOut,
  EnqueueIn,
  EventOut,
  FirstLoginOut,
  Health,
  JobOut,
  PublicationOut,
  ProxyIn,
  ProxyOut,
  ProxyUpdate,
  UploadOut,
  VideoOut,
} from "./types";

const RAW_BASE = (import.meta.env.VITE_API_BASE ?? "").trim();
export const API_BASE = RAW_BASE.replace(/\/$/, "");
const BASE = API_BASE;

export class ApiError extends Error {
  status: number;
  data: unknown;
  constructor(status: number, message: string, data?: unknown) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

/** User-facing API error text with hints for common status codes. */
export function formatApiError(err: unknown): string {
  if (!(err instanceof ApiError)) {
    return err instanceof Error ? err.message : "Неизвестная ошибка";
  }
  const detail = err.message;
  if (err.status === 405 || detail.toLowerCase().includes("method not allowed")) {
    return (
      "Метод не разрешён (405). Не открывайте API-URL в адресной строке браузера — " +
      "используйте кнопку «Создать сессию» в модале. Обновите страницу (Ctrl+Shift+R)."
    );
  }
  if (err.status === 401) {
    return "Требуется авторизация (401). Войдите в панель с ADMIN_TOKEN.";
  }
  if (err.status === 503 && detail.toLowerCase().includes("playwright")) {
    return `${detail} Выполните на сервере: docker compose exec reels-api python -m app.cli install-playwright`;
  }
  return detail || `HTTP ${err.status}`;
}

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

interface RequestOptions {
  method?: Method;
  body?: unknown;
  formData?: FormData;
  query?: Record<string, string | number | boolean | undefined | null>;
  signal?: AbortSignal;
}

let tokenGetter: () => string | null = () => null;

export function configureAuth(getter: () => string | null) {
  tokenGetter = getter;
}

export function getAuthHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  const token = tokenGetter();
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const url = `${BASE}${path}`;
  if (!query) return url;
  const params = new URLSearchParams();
  Object.entries(query).forEach(([k, v]) => {
    if (v === undefined || v === null || v === "") return;
    params.append(k, String(v));
  });
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {};
  const token = tokenGetter();
  if (token) headers.Authorization = `Bearer ${token}`;

  let body: BodyInit | undefined;
  if (opts.formData) {
    body = opts.formData;
  } else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }

  const method = opts.method ?? "GET";

  const res = await fetch(buildUrl(path, opts.query), {
    method,
    headers,
    body,
    signal: opts.signal,
    redirect: method === "GET" ? "follow" : "manual",
  });

  if (method !== "GET" && res.status >= 300 && res.status < 400) {
    throw new ApiError(
      res.status,
      "Запрос был перенаправлен — обновите страницу (Ctrl+Shift+R) или проверьте nginx (POST не должен редиректиться в GET)",
      null
    );
  }

  if (!res.ok) {
    let detail: unknown = null;
    const cloned = res.clone();
    try {
      detail = await res.json();
    } catch {
      try {
        detail = await cloned.text();
      } catch {
        detail = null;
      }
    }
    const message =
      (detail && typeof detail === "object" && "detail" in detail
        ? String((detail as { detail: unknown }).detail)
        : typeof detail === "string"
          ? detail
          : `HTTP ${res.status}`) || `HTTP ${res.status}`;
    throw new ApiError(res.status, message, detail);
  }

  if (res.status === 204) return undefined as T;
  const ct = res.headers.get("content-type") ?? "";
  if (ct.includes("application/json")) {
    return (await res.json()) as T;
  }
  return undefined as T;
}

async function downloadFile(path: string, filename: string): Promise<void> {
  const res = await fetch(buildUrl(path), {
    method: "GET",
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    let detail: unknown = null;
    try {
      detail = await res.json();
    } catch {
      detail = await res.text().catch(() => null);
    }
    const message =
      (detail && typeof detail === "object" && "detail" in detail
        ? String((detail as { detail: unknown }).detail)
        : typeof detail === "string"
          ? detail
          : `HTTP ${res.status}`) || `HTTP ${res.status}`;
    throw new ApiError(res.status, message, detail);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

/** Fetch a binary resource and return an object URL (caller must revoke). */
async function fetchObjectUrl(path: string): Promise<string> {
  const res = await fetch(buildUrl(path), {
    method: "GET",
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    let detail: unknown = null;
    try {
      detail = await res.json();
    } catch {
      detail = await res.text().catch(() => null);
    }
    const message =
      (detail && typeof detail === "object" && "detail" in detail
        ? String((detail as { detail: unknown }).detail)
        : typeof detail === "string"
          ? detail
          : `HTTP ${res.status}`) || `HTTP ${res.status}`;
    throw new ApiError(res.status, message, detail);
  }
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}

export const api = {
  health: () => request<Health>("/api/health"),
  dashboard: () => request<DashboardSummary>("/api/dashboard"),

  accounts: {
    list: () => request<AccountOut[]>("/api/accounts"),
    create: (payload: AccountIn) =>
      request<AccountOut>("/api/accounts", { method: "POST", body: payload }),
    updateProxy: (username: string, payload: AccountProxyUpdate) =>
      request<AccountOut>(
        `/api/accounts/${encodeURIComponent(username)}/proxy`,
        { method: "PUT", body: payload }
      ),
    updateNotes: (username: string, payload: AccountNotesUpdate) =>
      request<AccountOut>(
        `/api/accounts/${encodeURIComponent(username)}/notes`,
        { method: "PATCH", body: payload }
      ),
    updateSession: (username: string, payload: AccountSessionUpdate) =>
      request<AccountOut>(
        `/api/accounts/${encodeURIComponent(username)}/session`,
        { method: "PUT", body: payload }
      ),
    getSession: (username: string) =>
      request<AccountSessionOut>(
        `/api/accounts/${encodeURIComponent(username)}/session`
      ),
    pause: (username: string) =>
      request<AccountOut>(
        `/api/accounts/${encodeURIComponent(username)}/pause`,
        { method: "POST" }
      ),
    resume: (username: string) =>
      request<AccountOut>(
        `/api/accounts/${encodeURIComponent(username)}/resume`,
        { method: "POST" }
      ),
    testConnection: (username: string) =>
      request<AccountConnectionTestOut>(
        `/api/accounts/${encodeURIComponent(username)}/test-connection`,
        { method: "POST" }
      ),
    firstLogin: (username: string, opts?: { loginSurface?: import("./types").LoginSurface }) =>
      request<FirstLoginOut>(
        `/api/accounts/${encodeURIComponent(username)}/first-login`,
        {
          method: "POST",
          query: opts?.loginSurface ? { login_surface: opts.loginSurface } : undefined,
        }
      ),
    exportCookies: (username: string) =>
      downloadFile(
        `/api/accounts/${encodeURIComponent(username)}/cookies/export`,
        `cookies_${username}.json`
      ),
    exportPlaywrightState: (username: string) =>
      downloadFile(
        `/api/accounts/${encodeURIComponent(username)}/playwright-state`,
        `state_${username}.json`
      ),
    fetchLoginDebugScreenshot: (username: string) =>
      fetchObjectUrl(
        `/api/accounts/${encodeURIComponent(username)}/login-debug-screenshot`
      ),
    browserStart: (username: string, opts?: { loginSurface?: import("./types").LoginSurface }) =>
      request<BrowserSessionOut>(
        `/api/accounts/${encodeURIComponent(username)}/browser/start`,
        {
          method: "POST",
          query: opts?.loginSurface ? { login_surface: opts.loginSurface } : undefined,
        }
      ),
    browserOpenInstagram: (username: string, opts?: { autofill?: boolean }) =>
      request<BrowserSessionOut>(
        `/api/accounts/${encodeURIComponent(username)}/browser/open-instagram`,
        {
          method: "POST",
          query: opts?.autofill ? { autofill: true } : undefined,
        }
      ),
    browserStatus: (username: string) =>
      request<BrowserSessionOut>(
        `/api/accounts/${encodeURIComponent(username)}/browser/status`
      ),
    browserSubmitCode: (username: string, code: string | null) =>
      request<BrowserSessionOut>(
        `/api/accounts/${encodeURIComponent(username)}/browser/code`,
        { method: "POST", body: { code } }
      ),
    browserSave: (username: string, opts?: { stopAfterSave?: boolean }) =>
      request<BrowserSaveOut>(
        `/api/accounts/${encodeURIComponent(username)}/browser/save`,
        {
          method: "POST",
          query: opts?.stopAfterSave ? { stop_after_save: true } : undefined,
        }
      ),
    browserStop: (username: string) =>
      request<BrowserSessionOut>(
        `/api/accounts/${encodeURIComponent(username)}/browser/stop`,
        { method: "DELETE" }
      ),
    exportDeviceFingerprint: (username: string) =>
      downloadFile(
        `/api/accounts/${encodeURIComponent(username)}/device-fingerprint`,
        `device_${username}.json`
      ),
    importCookiesFile: (username: string, file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      return request<CookiesImportOut>(
        `/api/accounts/${encodeURIComponent(username)}/cookies/import`,
        { method: "POST", formData: fd }
      );
    },
  },

  proxies: {
    list: () => request<ProxyOut[]>("/api/proxies"),
    create: (payload: ProxyIn) =>
      request<ProxyOut>("/api/proxies", { method: "POST", body: payload }),
    update: (label: string, payload: ProxyUpdate) =>
      request<ProxyOut>(`/api/proxies/${encodeURIComponent(label)}`, {
        method: "PUT",
        body: payload,
      }),
    remove: (label: string) =>
      request<{ ok: boolean }>(`/api/proxies/${encodeURIComponent(label)}`, {
        method: "DELETE",
      }),
    check: (label: string) =>
      request<ProxyOut>(
        `/api/proxies/${encodeURIComponent(label)}/check`,
        { method: "POST" }
      ),
  },

  videos: {
    list: () => request<VideoOut[]>("/api/videos"),
    mediaPath: (filename: string) =>
      `${BASE}/api/videos/${encodeURIComponent(filename)}`,
    upload: (file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      return request<UploadOut>("/api/videos", { method: "POST", formData: fd });
    },
    remove: (filename: string) =>
      request<{ ok: boolean }>(`/api/videos/${encodeURIComponent(filename)}`, {
        method: "DELETE",
      }),
  },

  jobs: {
    list: (params?: { status?: string; username?: string; limit?: number }) =>
      request<JobOut[]>("/api/jobs", { query: params }),
    enqueue: (payload: EnqueueIn) =>
      request<JobOut>("/api/jobs", { method: "POST", body: payload }),
    cancel: (id: number) =>
      request<JobOut>(`/api/jobs/${id}/cancel`, { method: "POST" }),
    logs: (id: number) => request<DiagnosticRunOut[]>(`/api/jobs/${id}/logs`),
  },

  diagnostics: {
    list: (params?: {
      username?: string;
      kind?: string;
      job_id?: number;
      limit?: number;
    }) => request<DiagnosticRunOut[]>("/api/diagnostic-runs", { query: params }),
    get: (id: number) => request<DiagnosticRunOut>(`/api/diagnostic-runs/${id}`),
  },

  events: {
    list: (params?: {
      level?: string;
      kind?: string;
      username?: string;
      limit?: number;
    }) => request<EventOut[]>("/api/events", { query: params }),
  },

  publications: {
    list: (params?: { username?: string; limit?: number }) =>
      request<PublicationOut[]>("/api/publications", { query: params }),
    refreshStats: (id: number) =>
      request<PublicationOut>(`/api/publications/${id}/refresh-stats`, {
        method: "POST",
      }),
  },
};
