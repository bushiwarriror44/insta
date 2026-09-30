import type {
  AccountConnectionTestOut,
  AccountIn,
  AccountNotesUpdate,
  AccountOut,
  AccountProxyUpdate,
  AccountSessionOut,
  AccountSessionUpdate,
  AccountTotpOut,
  BrowserSaveOut,
  BrowserSessionOut,
  CookiesImportOut,
  DeviceFingerprintImportOut,
  DashboardSummary,
  DiagnosticRunOut,
  EnqueueIn,
  EventOut,
  FirstLoginOut,
  Health,
  JobOut,
  MintMobileSessionOut,
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
    const msg = err instanceof Error ? err.message : "Неизвестная ошибка";
    if (/networkerror|failed to fetch|network request failed|load failed/i.test(msg)) {
      return (
        "Сеть оборвала загрузку (NetworkError). Проверьте соединение, VPN и что API доступен; " +
        "при мультизагрузке остальные файлы продолжат грузиться."
      );
    }
    return msg;
  }
  const detail = err.message;
  if (err.status === 0) {
    return (
      detail ||
      "Сеть оборвала загрузку. Проверьте соединение и лимиты прокси/nginx, затем повторите."
    );
  }
  if (err.status === 405 || detail.toLowerCase().includes("method not allowed")) {
    return (
      "Метод не разрешён (405). Не открывайте API-URL в адресной строке браузера — " +
      "используйте кнопку «Создать сессию» в модале. Обновите страницу (Ctrl+Shift+R)."
    );
  }
  if (err.status === 401) {
    const genericAuth =
      !detail ||
      /^unauthorized$/i.test(detail) ||
      /missing or invalid authorization/i.test(detail);
    if (!genericAuth) {
      return detail;
    }
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

export type UploadProgressCallback = (loaded: number, total: number) => void;

function parseXhrErrorDetail(xhr: XMLHttpRequest): string {
  const raw = xhr.responseText || "";
  if (!raw) {
    if (xhr.status === 0) {
      return "Сеть оборвала загрузку (соединение сброшено или CORS/прокси)";
    }
    return xhr.statusText || `HTTP ${xhr.status}`;
  }
  try {
    const parsed = JSON.parse(raw) as { detail?: unknown };
    if (parsed && typeof parsed === "object" && "detail" in parsed) {
      return String(parsed.detail);
    }
  } catch {
    /* plain text */
  }
  return raw.slice(0, 300) || `HTTP ${xhr.status}`;
}

/** Upload via XHR so browsers can report upload progress (fetch cannot). */
export function uploadWithProgress(
  file: File,
  opts?: {
    compress?: boolean;
    onProgress?: UploadProgressCallback;
    signal?: AbortSignal;
  }
): Promise<UploadOut> {
  const fd = new FormData();
  fd.append("file", file);
  const compress = opts?.compress ?? true;
  fd.append("compress", compress ? "true" : "false");

  return new Promise<UploadOut>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", buildUrl("/api/videos"));
    const token = tokenGetter();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);

    xhr.upload.onprogress = (ev) => {
      if (!opts?.onProgress) return;
      const total = ev.lengthComputable ? ev.total : file.size;
      opts.onProgress(ev.loaded, total || file.size);
    };

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const data = JSON.parse(xhr.responseText || "{}") as UploadOut;
          resolve(data);
        } catch (err) {
          reject(
            new ApiError(xhr.status, "Некорректный ответ сервера при загрузке", err)
          );
        }
        return;
      }
      reject(new ApiError(xhr.status, parseXhrErrorDetail(xhr)));
    };

    xhr.onerror = () => {
      reject(
        new ApiError(
          0,
          "Сеть оборвала загрузку (NetworkError). Проверьте соединение и доступность API."
        )
      );
    };

    xhr.ontimeout = () => {
      reject(new ApiError(0, "Таймаут загрузки файла. Повторите попытку."));
    };

    xhr.onabort = () => {
      reject(new ApiError(0, "Загрузка отменена"));
    };

    if (opts?.signal) {
      if (opts.signal.aborted) {
        xhr.abort();
        return;
      }
      const onAbort = () => xhr.abort();
      opts.signal.addEventListener("abort", onAbort, { once: true });
      xhr.addEventListener("loadend", () => {
        opts.signal?.removeEventListener("abort", onAbort);
      });
    }

    xhr.send(fd);
  });
}

async function downloadFile(
  path: string,
  filename: string,
  opts?: { method?: string; body?: unknown }
): Promise<void> {
  const headers: Record<string, string> = { ...getAuthHeaders() };
  let body: BodyInit | undefined;
  if (opts?.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  const res = await fetch(buildUrl(path), {
    method: opts?.method ?? "GET",
    headers,
    body,
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
  const disposition = res.headers.get("content-disposition") ?? "";
  const match = /filename\*?=(?:UTF-8''|")?([^";]+)/i.exec(disposition);
  const downloadName = match
    ? decodeURIComponent(match[1].replace(/"/g, "").trim())
    : filename;
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = downloadName;
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
    getTotp: (username: string) =>
      request<AccountTotpOut>(
        `/api/accounts/${encodeURIComponent(username)}/totp`
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
    testConnection: (
      username: string,
      opts?: { probeMobile?: boolean }
    ) =>
      request<AccountConnectionTestOut>(
        `/api/accounts/${encodeURIComponent(username)}/test-connection`,
        {
          method: "POST",
          query:
            opts?.probeMobile === true
              ? { probe_mobile: "true" }
              : opts?.probeMobile === false
                ? { probe_mobile: "false" }
                : undefined,
        }
      ),
    firstLogin: (username: string, opts?: { loginSurface?: import("./types").LoginSurface }) =>
      request<FirstLoginOut>(
        `/api/accounts/${encodeURIComponent(username)}/first-login`,
        {
          method: "POST",
          query: opts?.loginSurface ? { login_surface: opts.loginSurface } : undefined,
        }
      ),
    mintMobileSession: (username: string) =>
      request<MintMobileSessionOut>(
        `/api/accounts/${encodeURIComponent(username)}/mint-mobile-session`,
        { method: "POST" }
      ),
    exportCookies: (username: string, format: "json" | "txt" = "json") =>
      downloadFile(
        `/api/accounts/${encodeURIComponent(username)}/cookies/export${
          format === "txt" ? "?format=txt" : ""
        }`,
        `cookies_${username}.${format === "txt" ? "txt" : "json"}`
      ),
    exportPlaywrightState: (username: string, format: "json" | "txt" = "json") =>
      downloadFile(
        `/api/accounts/${encodeURIComponent(username)}/playwright-state${
          format === "txt" ? "?format=txt" : ""
        }`,
        `state_${username}.${format === "txt" ? "txt" : "json"}`
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
    browserOpenInstagram: (
      username: string,
      opts?: {
        autofill?: boolean;
        target?:
          | "auto"
          | "login"
          | "home"
          | "reels"
          | "explore"
          | "direct"
          | "activity"
          | "profile"
          | "edit_profile";
      }
    ) =>
      request<BrowserSessionOut>(
        `/api/accounts/${encodeURIComponent(username)}/browser/open-instagram`,
        {
          method: "POST",
          query: {
            ...(opts?.autofill ? { autofill: true } : {}),
            ...(opts?.target && opts.target !== "auto" ? { target: opts.target } : {}),
          },
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
    exportDeviceFingerprint: (username: string, format: "json" | "txt" = "json") =>
      downloadFile(
        `/api/accounts/${encodeURIComponent(username)}/device-fingerprint${
          format === "txt" ? "?format=txt" : ""
        }`,
        `device_${username}.${format === "txt" ? "txt" : "json"}`
      ),
    importCookiesFile: (username: string, file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      return request<CookiesImportOut>(
        `/api/accounts/${encodeURIComponent(username)}/cookies/import`,
        { method: "POST", formData: fd }
      );
    },
    importDeviceFingerprint: (username: string, file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      return request<DeviceFingerprintImportOut>(
        `/api/accounts/${encodeURIComponent(username)}/device-fingerprint`,
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
    upload: (
      file: File,
      opts?: {
        compress?: boolean;
        onProgress?: UploadProgressCallback;
        signal?: AbortSignal;
      }
    ) => uploadWithProgress(file, opts),
    download: (filename: string) =>
      downloadFile(`/api/videos/${encodeURIComponent(filename)}`, filename),
    downloadArchive: (filenames: string[]) =>
      downloadFile("/api/videos/archive", "media.zip", {
        method: "POST",
        body: { filenames },
      }),
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
    approve: (id: number) =>
      request<JobOut>(`/api/jobs/${id}/approve`, { method: "POST" }),
    retry: (id: number) =>
      request<JobOut>(`/api/jobs/${id}/retry`, { method: "POST" }),
    reschedule: (id: number, when: string) =>
      request<JobOut>(`/api/jobs/${id}`, { method: "PATCH", body: { when } }),
    logs: (id: number) => request<DiagnosticRunOut[]>(`/api/jobs/${id}/logs`),
  },

  factory: {
    plan: (accountId: number, body?: { count?: number; duration_s?: number; auto_schedule?: boolean; spread_over_days?: number }) =>
      request<{ id: number; status: string }>(`/api/accounts/${accountId}/plan`, {
        method: "POST",
        body: body ?? { count: 5 },
      }),
    week: (accountId: number, body?: { count?: number; duration_s?: number; auto_schedule?: boolean }) =>
      request<{ id: number; status: string }>(`/api/accounts/${accountId}/week`, {
        method: "POST",
        body: body ?? { count: 5 },
      }),
    preview: (accountId: number, body?: { count?: number; duration_s?: number }) =>
      request<{ planned: number }>(`/api/accounts/${accountId}/preview`, {
        method: "POST",
        body: body ?? { count: 3 },
      }),
    updateBrief: (accountId: number, brief: string) =>
      request<{ brief: string }>(`/api/accounts/${accountId}/brief`, {
        method: "PATCH",
        body: { brief },
      }),
    updateAgentSettings: (
      accountId: number,
      body: { brief?: string; hold_for_review?: boolean; daily_spend_cap_usd?: number }
    ) =>
      request<{ id: number; brief: string; hold_for_review: boolean; daily_spend_cap_usd: number }>(
        `/api/accounts/${accountId}/agent-settings`,
        { method: "PATCH", body }
      ),
    sources: (accountId: number) =>
      request<Array<{ id: number; kind: string; value: string; label: string; enabled: boolean; last_status: string }>>(
        `/api/accounts/${accountId}/sources`
      ),
    addSource: (accountId: number, body: { kind: string; value: string; label?: string }) =>
      request<{ id: number }>(`/api/accounts/${accountId}/sources`, { method: "POST", body }),
    patchSource: (sourceId: number, body: { enabled?: boolean; label?: string }) =>
      request<{ id: number; enabled: boolean }>(`/api/sources/${sourceId}`, { method: "PATCH", body }),
    checkSource: (sourceId: number) =>
      request<{ id: number; last_status: string }>(`/api/sources/${sourceId}/check`, { method: "POST" }),
    readSource: (sourceId: number) =>
      request<{ text: string; characters: number }>(`/api/sources/${sourceId}/read`, { method: "POST" }),
    questions: (accountId: number) =>
      request<Array<{ id: number; question: string; why: string; assumed: string; open: boolean }>>(
        `/api/accounts/${accountId}/questions`
      ),
    answerQuestion: (questionId: number, answer: string) =>
      request<{ id: number }>(`/api/questions/${questionId}/answer`, { method: "POST", body: { answer } }),
    presets: () => request<Array<{ id: number; name: string; brief: string }>>("/api/presets"),
    assets: (params?: { kind?: string; q?: string; limit?: number }) =>
      request<import("./types").MediaAssetOut[]>("/api/assets", { query: params }),
    agentRuns: (accountId?: number) =>
      request<Array<{ id: number; account_username: string | null; ok: boolean; model: string; requested: number; returned: number; cost_usd: number; error: string | null; created_at: string }>>(
        "/api/agent-runs",
        { query: accountId ? { account_id: accountId } : undefined }
      ),
    agentRun: (id: number) =>
      request<{
        id: number;
        ok: boolean;
        prompt: string;
        raw: string;
        ideas: unknown;
        questions: unknown;
        sources: unknown;
        error: string | null;
        cost_usd: number;
        duration_ms: number;
      }>(`/api/agent-runs/${id}`),
    generations: () =>
      request<Array<{ id: number; status: string; prompt: string; stage: string; post_title: string; last_error: string | null; cost_usd: number; backend?: string }>>(
        "/api/generations"
      ),
    backends: () => request<import("./types").RenderBackendOut[]>("/api/generations/backends"),
    createGeneration: (body: {
      prompt: string;
      account_id?: number;
      duration_s?: number;
      backend?: string;
      input_mode?: string;
      reference_asset_id?: number;
      reference_filename?: string;
      reference_role?: string;
    }) => request<{ id: number; status: string }>("/api/generations", { method: "POST", body }),
    cancelGeneration: (id: number) =>
      request<{ id: number; status: string }>(`/api/generations/${id}/cancel`, { method: "POST" }),
    retryGeneration: (id: number) =>
      request<{ id: number; status: string }>(`/api/generations/${id}/retry`, { method: "POST" }),
    compositions: () =>
      request<Array<{ id: number; status: string; post_title: string; last_error: string | null; clips: number }>>(
        "/api/compositions"
      ),
    createComposition: (body: { clip_ids: number[]; audio_asset_id?: number; account_id?: number; post_title?: string }) =>
      request<{ id: number; status: string }>("/api/compositions", { method: "POST", body }),
    cancelComposition: (id: number) =>
      request<{ id: number; status: string }>(`/api/compositions/${id}/cancel`, { method: "POST" }),
    retryComposition: (id: number) =>
      request<{ id: number; status: string }>(`/api/compositions/${id}/retry`, { method: "POST" }),
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

  auth: {
    me: () => request<import("./types").AuthMeOut>("/api/auth/me"),
  },

  panel: {
    gate: (path: string) =>
      request<import("./types").PanelGateOut>("/api/panel/gate", {
        query: { path },
      }),
  },

  settings: {
    get: () => request<import("./types").PanelSettingsOut>("/api/settings"),
    updateEntryPath: (path: string, currentPassword: string) =>
      request<import("./types").PanelSettingsOut>("/api/settings/entry-path", {
        method: "PUT",
        body: { path, current_password: currentPassword },
      }),
    updateMasterPassword: (currentPassword: string, newPassword: string) =>
      request<import("./types").PanelSettingsOut>("/api/settings/master-password", {
        method: "PUT",
        body: {
          current_password: currentPassword,
          new_password: newPassword,
        },
      }),
  },

  operators: {
    list: () => request<import("./types").PanelOperatorOut[]>("/api/operators"),
    create: (label: string) =>
      request<import("./types").PanelOperatorCreatedOut>("/api/operators", {
        method: "POST",
        body: { label },
      }),
    revoke: (id: number) =>
      request<import("./types").PanelOperatorOut>(`/api/operators/${id}/revoke`, {
        method: "POST",
      }),
  },

  worker: {
    status: () => request<import("./types").WorkerProcessOut>("/api/worker"),
    start: () => request<import("./types").WorkerProcessOut>("/api/worker/start", { method: "POST" }),
    stop: () => request<import("./types").WorkerProcessOut>("/api/worker/stop", { method: "POST" }),
  },

  gpu: {
    status: () => request<import("./types").GpuOut>("/api/gpu"),
    start: () => request<import("./types").GpuOut>("/api/gpu/start", { method: "POST" }),
    stop: () => request<import("./types").GpuOut>("/api/gpu/stop", { method: "POST" }),
  },

  adminNotes: {
    get: () => request<import("./types").AdminNotesOut>("/api/admin-notes"),
    update: (content: string) =>
      request<import("./types").AdminNotesOut>("/api/admin-notes", {
        method: "PUT",
        body: { content },
      }),
  },

  maintenance: {
    runtime: () => request<import("./types").RuntimeOut>("/api/maintenance/runtime"),
    setContext: (context: number, model?: string) =>
      request<import("./types").RuntimeOut>("/api/maintenance/runtime/context", {
        method: "POST",
        body: { context, model },
      }),
    backups: () => request<import("./types").BackupOut[]>("/api/maintenance/backups"),
    takeBackup: () =>
      request<import("./types").BackupOut>("/api/maintenance/backups", { method: "POST" }),
  },
};
