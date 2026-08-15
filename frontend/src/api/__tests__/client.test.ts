import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  api,
  configureAuth,
  formatApiError,
  uploadWithProgress,
} from "../client";

interface FakeResponseInit {
  status?: number;
  body?: unknown;
  json?: unknown;
  text?: string;
  contentType?: string | null;
}

function makeResponse({
  status = 200,
  json,
  text,
  contentType,
}: FakeResponseInit): Response {
  const headers = new Headers();
  if (contentType !== null) {
    headers.set(
      "content-type",
      contentType ?? (json !== undefined ? "application/json" : "text/plain")
    );
  }
  const bodyText =
    json !== undefined ? JSON.stringify(json) : text !== undefined ? text : "";
  return new Response(status === 204 ? null : bodyText, { status, headers });
}

let fetchSpy: ReturnType<typeof vi.spyOn>;

function getCall(index = 0) {
  const call = fetchSpy.mock.calls[index];
  if (!call) throw new Error(`fetch was not called at index ${index}`);
  const url = call[0] as string;
  const init = (call[1] ?? {}) as RequestInit;
  return { url, init };
}

type FakeXhrInstance = {
  open: ReturnType<typeof vi.fn>;
  setRequestHeader: ReturnType<typeof vi.fn>;
  send: ReturnType<typeof vi.fn>;
  abort: ReturnType<typeof vi.fn>;
  addEventListener: ReturnType<typeof vi.fn>;
  upload: { onprogress: ((ev: ProgressEvent) => void) | null };
  onload: (() => void) | null;
  onerror: (() => void) | null;
  ontimeout: (() => void) | null;
  onabort: (() => void) | null;
  status: number;
  statusText: string;
  responseText: string;
};

let lastXhr: FakeXhrInstance | null = null;
let xhrInstances: FakeXhrInstance[] = [];

function installXhrMock(opts?: {
  status?: number;
  responseText?: string;
  trigger?: "load" | "error";
  progress?: Array<{ loaded: number; total: number }>;
}) {
  const status = opts?.status ?? 200;
  const responseText =
    opts?.responseText ??
    JSON.stringify({ filename: "x.mp4", size_bytes: 4, media_type: "video" });
  const trigger = opts?.trigger ?? "load";
  const progress = opts?.progress ?? [{ loaded: 2, total: 4 }];

  class FakeXHR {
    open = vi.fn();
    setRequestHeader = vi.fn();
    abort = vi.fn();
    addEventListener = vi.fn();
    upload: { onprogress: ((ev: ProgressEvent) => void) | null } = { onprogress: null };
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    ontimeout: (() => void) | null = null;
    onabort: (() => void) | null = null;
    status = status;
    statusText = status >= 200 && status < 300 ? "OK" : "Error";
    responseText = responseText;

    send = vi.fn(() => {
      queueMicrotask(() => {
        for (const p of progress) {
          this.upload.onprogress?.({
            lengthComputable: true,
            loaded: p.loaded,
            total: p.total,
          } as ProgressEvent);
        }
        if (trigger === "error") this.onerror?.();
        else this.onload?.();
      });
    });
  }

  xhrInstances = [];
  vi.stubGlobal(
    "XMLHttpRequest",
    vi.fn(function (this: FakeXhrInstance) {
      const inst = new FakeXHR() as unknown as FakeXhrInstance;
      lastXhr = inst;
      xhrInstances.push(inst);
      return inst;
    })
  );
}

beforeEach(() => {
  configureAuth(() => null);
  fetchSpy = vi.spyOn(window, "fetch");
  lastXhr = null;
  xhrInstances = [];
});

afterEach(() => {
  fetchSpy.mockRestore();
  vi.unstubAllGlobals();
});

describe("api.health", () => {
  it("calls /api/health and returns parsed body", async () => {
    fetchSpy.mockResolvedValueOnce(
      makeResponse({ json: { ok: true, version: "x", auth_required: false } })
    );
    const out = await api.health();
    expect(out).toEqual({ ok: true, version: "x", auth_required: false });
    const { url, init } = getCall();
    expect(url).toBe("/api/health");
    expect(init.method ?? "GET").toBe("GET");
  });
});

describe("auth header", () => {
  it("does NOT send Authorization when token getter returns null", async () => {
    fetchSpy.mockResolvedValueOnce(makeResponse({ json: {} }));
    await api.dashboard();
    const headers = (getCall().init.headers ?? {}) as Record<string, string>;
    expect(headers.Authorization).toBeUndefined();
  });

  it("injects Bearer token when configureAuth provides one", async () => {
    configureAuth(() => "tok-1");
    fetchSpy.mockResolvedValueOnce(makeResponse({ json: {} }));
    await api.dashboard();
    const headers = (getCall().init.headers ?? {}) as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer tok-1");
  });
});

describe("query params", () => {
  it("skips undefined / null / empty-string values", async () => {
    fetchSpy.mockResolvedValueOnce(makeResponse({ json: [] }));
    await api.events.list({ level: "warn", username: "", limit: undefined });
    const { url } = getCall();
    expect(url).toBe("/api/events?level=warn");
  });

  it("appends multiple query params correctly", async () => {
    fetchSpy.mockResolvedValueOnce(makeResponse({ json: [] }));
    await api.jobs.list({ status: "queued", username: "alice", limit: 25 });
    const { url } = getCall();
    expect(url).toBe("/api/jobs?status=queued&username=alice&limit=25");
  });
});

describe("body serialization", () => {
  it("serializes JSON body and sets Content-Type", async () => {
    fetchSpy.mockResolvedValueOnce(makeResponse({ json: { id: 1 } }));
    await api.proxies.create({
      label: "p-1",
      url: "http://h",
      skip_health_check: true,
    });
    const { url, init } = getCall();
    expect(url).toBe("/api/proxies");
    expect(init.method).toBe("POST");
    expect(init.body).toBe(
      JSON.stringify({ label: "p-1", url: "http://h", skip_health_check: true })
    );
    const headers = init.headers as Record<string, string>;
    expect(headers["Content-Type"]).toBe("application/json");
  });

  it("uploads via XHR with FormData compress=true by default", async () => {
    installXhrMock({
      responseText: JSON.stringify({
        filename: "x.mp4",
        size_bytes: 4,
        media_type: "video",
      }),
    });
    const file = new File([new Uint8Array([1, 2, 3, 4])], "clip.mp4", {
      type: "video/mp4",
    });
    const out = await api.videos.upload(file);
    expect(out.filename).toBe("x.mp4");
    expect(lastXhr?.open).toHaveBeenCalledWith("POST", "/api/videos");
    const sent = lastXhr?.send.mock.calls[0]?.[0] as FormData;
    expect(sent).toBeInstanceOf(FormData);
    expect(sent.get("compress")).toBe("true");
    expect(sent.get("file")).toBeTruthy();
  });

  it("sends compress=false when upload opts disable compression", async () => {
    installXhrMock({
      responseText: JSON.stringify({
        filename: "p.jpg",
        size_bytes: 10,
        media_type: "image",
      }),
    });
    const file = new File([new Uint8Array([1, 2, 3])], "p.jpg", {
      type: "image/jpeg",
    });
    await api.videos.upload(file, { compress: false });
    const sent = lastXhr?.send.mock.calls[0]?.[0] as FormData;
    expect(sent.get("compress")).toBe("false");
  });

  it("uploadWithProgress reports progress callbacks", async () => {
    installXhrMock({
      progress: [
        { loaded: 1, total: 4 },
        { loaded: 4, total: 4 },
      ],
      responseText: JSON.stringify({
        filename: "clip.mp4",
        size_bytes: 4,
        media_type: "video",
      }),
    });
    const onProgress = vi.fn();
    const file = new File([new Uint8Array([1, 2, 3, 4])], "clip.mp4", {
      type: "video/mp4",
    });
    await uploadWithProgress(file, { onProgress });
    expect(onProgress).toHaveBeenCalledWith(1, 4);
    expect(onProgress).toHaveBeenCalledWith(4, 4);
  });

  it("uploadWithProgress maps network failure to ApiError status 0", async () => {
    installXhrMock({ trigger: "error" });
    const file = new File([new Uint8Array([1])], "a.mp4", { type: "video/mp4" });
    await expect(uploadWithProgress(file)).rejects.toMatchObject({
      status: 0,
      message: expect.stringMatching(/сеть|network/i),
    });
  });

  it("downloads media archive via POST /api/videos/archive", async () => {
    const createObjectURL = vi.fn(() => "blob:zip");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL,
      revokeObjectURL,
    });
    const clickSpy = vi.fn();
    const anchor = document.createElement("a");
    anchor.click = clickSpy;
    vi.spyOn(document, "createElement").mockReturnValue(anchor);
    vi.spyOn(document.body, "appendChild").mockImplementation(() => anchor);

    fetchSpy.mockResolvedValueOnce(
      new Response(new Uint8Array([0x50, 0x4b]), {
        status: 200,
        headers: {
          "content-type": "application/zip",
          "content-disposition": 'attachment; filename="media-test.zip"',
        },
      })
    );

    await api.videos.downloadArchive(["a.jpg", "b.mp4"]);
    const { url, init } = getCall();
    expect(url).toBe("/api/videos/archive");
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify({ filenames: ["a.jpg", "b.mp4"] }));
    expect(clickSpy).toHaveBeenCalled();
    expect(anchor.download).toBe("media-test.zip");
  });

  it("serializes full accounts.create payload as JSON", async () => {
    fetchSpy.mockResolvedValueOnce(makeResponse({ json: { id: 1 } }));
    await api.accounts.create({
      username: "alice",
      password: "secret",
      proxy_label: "res-de-1",
      timezone: "Europe/Berlin",
      daily_post_cap: 4,
      min_gap_hours: 5.5,
      active_hour_start: 11,
      active_hour_end: 23,
      caption_profile: "travel",
      totp_seed: "JBSWY3DPEHPK3PXP",
      email: "alice@example.com",
      email_password: "mailpass",
    });
    const { url, init } = getCall();
    expect(url).toBe("/api/accounts");
    expect(init.method).toBe("POST");
    expect(init.body).toBe(
      JSON.stringify({
        username: "alice",
        password: "secret",
        proxy_label: "res-de-1",
        timezone: "Europe/Berlin",
        daily_post_cap: 4,
        min_gap_hours: 5.5,
        active_hour_start: 11,
        active_hour_end: 23,
        caption_profile: "travel",
        totp_seed: "JBSWY3DPEHPK3PXP",
        email: "alice@example.com",
        email_password: "mailpass",
      })
    );
  });

  it("serializes account proxy update payload as JSON", async () => {
    fetchSpy.mockResolvedValueOnce(makeResponse({ json: { id: 1 } }));
    await api.accounts.updateProxy("alice", { proxy_label: "res-us-1" });
    const { url, init } = getCall();
    expect(url).toBe("/api/accounts/alice/proxy");
    expect(init.method).toBe("PUT");
    expect(init.body).toBe(JSON.stringify({ proxy_label: "res-us-1" }));
    const headers = init.headers as Record<string, string>;
    expect(headers["Content-Type"]).toBe("application/json");
  });

  it("serializes account session update payload as JSON", async () => {
    fetchSpy.mockResolvedValueOnce(makeResponse({ json: { id: 1 } }));
    const sessionId = "a".repeat(40);
    await api.accounts.updateSession("alice", { session_id: sessionId });
    const { url, init } = getCall();
    expect(url).toBe("/api/accounts/alice/session");
    expect(init.method).toBe("PUT");
    expect(init.body).toBe(JSON.stringify({ session_id: sessionId }));
    const headers = init.headers as Record<string, string>;
    expect(headers["Content-Type"]).toBe("application/json");
  });

  it("fetches account session via GET", async () => {
    fetchSpy.mockResolvedValueOnce(
      makeResponse({
        json: {
          session_id: "a".repeat(40),
          source: "database",
          session_file_exists: true,
        },
      })
    );
    const out = await api.accounts.getSession("alice");
    const { url, init } = getCall();
    expect(url).toBe("/api/accounts/alice/session");
    expect(init.method).toBe("GET");
    expect(out.source).toBe("database");
  });

  it("posts account test-connection", async () => {
    fetchSpy.mockResolvedValueOnce(
      makeResponse({
        json: {
          username: "alice",
          proxy_assigned: true,
          proxy_label: "px-1",
          proxy_health: {
            ok: true,
            ip: "1.2.3.4",
            geo_country: "US",
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
            ig_username: "alice",
            challenge: false,
          },
          overall_ok: true,
          checked_at: "2026-06-29T10:00:00Z",
        },
      })
    );
    const out = await api.accounts.testConnection("alice");
    const { url, init } = getCall();
    expect(url).toBe("/api/accounts/alice/test-connection");
    expect(init.method).toBe("POST");
    expect(out.overall_ok).toBe(true);
  });

  it("passes probe_mobile query when requested", async () => {
    fetchSpy.mockResolvedValueOnce(
      makeResponse({
        json: {
          username: "alice",
          proxy_assigned: true,
          proxy_health: { ok: true, instagram_reachable: true, geo_mismatch: false },
          session_storage: {
            has_session_id: true,
            session_file_exists: false,
            device_file_exists: true,
            session_source: "database",
          },
          instagram_auth: { ok: true, method: "sessionid", challenge: false },
          overall_ok: true,
          checked_at: "2026-06-29T10:00:00Z",
          run_id: 1,
          logs: [],
        },
      })
    );
    await api.accounts.testConnection("alice", { probeMobile: true });
    const { url } = getCall();
    expect(url).toContain("probe_mobile=true");
  });

  it("downloads cookies export as file", async () => {
    const createObjectURL = vi.fn(() => "blob:mock");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL,
      revokeObjectURL,
    });
    const clickSpy = vi.fn();
    const anchor = document.createElement("a");
    anchor.click = clickSpy;
    const createElSpy = vi.spyOn(document, "createElement").mockReturnValue(anchor);
    const appendSpy = vi.spyOn(document.body, "appendChild").mockImplementation(() => anchor);

    fetchSpy.mockResolvedValueOnce(
      new Response(JSON.stringify([{ name: "sessionid", value: "x" }]), {
        status: 200,
        headers: { "content-type": "application/json" },
      })
    );

    await api.accounts.exportCookies("alice");
    const { url } = getCall();
    expect(url).toBe("/api/accounts/alice/cookies/export");
    expect(clickSpy).toHaveBeenCalled();
    expect(anchor.download).toBe("cookies_alice.json");

    createElSpy.mockRestore();
    appendSpy.mockRestore();
    vi.unstubAllGlobals();
  });

  it("imports cookies file via multipart POST", async () => {
    fetchSpy.mockResolvedValueOnce(
      makeResponse({
        json: {
          format: "dolphin",
          session_id: "a".repeat(40),
          session_id_imported: true,
          playwright_state_saved: true,
          session_file_cleared: false,
        },
      })
    );
    const file = new File(['[{"name":"sessionid","value":"' + "a".repeat(40) + '"}]'], "c.json", {
      type: "application/json",
    });
    const out = await api.accounts.importCookiesFile("alice", file);
    const { url, init } = getCall();
    expect(url).toBe("/api/accounts/alice/cookies/import");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    expect(out.format).toBe("dolphin");
    expect(out.session_id).toBe("a".repeat(40));
  });

  it("mints mobile session via POST", async () => {
    fetchSpy.mockResolvedValueOnce(
      makeResponse({
        json: {
          run_id: 7,
          ok: true,
          challenge: false,
          session_id: "m".repeat(40),
          logs: [],
        },
      })
    );
    const out = await api.accounts.mintMobileSession("alice");
    const { url, init } = getCall();
    expect(url).toBe("/api/accounts/alice/mint-mobile-session");
    expect(init.method).toBe("POST");
    expect(out.ok).toBe(true);
    expect(out.session_id).toBe("m".repeat(40));
  });

  it("uses manual redirect for POST requests", async () => {
    fetchSpy.mockResolvedValueOnce(
      makeResponse({ status: 200, json: { run_id: 1, ok: true, logs: [] } })
    );
    await api.accounts.firstLogin("alice");
    const { init } = getCall();
    expect(init.method).toBe("POST");
    expect(init.redirect).toBe("manual");
  });

  it("rejects POST redirect responses", async () => {
    fetchSpy.mockResolvedValueOnce(
      new Response(null, { status: 302, headers: { Location: "/elsewhere" } })
    );
    await expect(api.accounts.firstLogin("alice")).rejects.toMatchObject({
      status: 302,
    });
  });
});

describe("response handling", () => {
  it("returns undefined for 204 No Content", async () => {
    fetchSpy.mockResolvedValueOnce(makeResponse({ status: 204, contentType: null }));
    const out = await api.videos.remove("a.mp4");
    expect(out).toBeUndefined();
  });

  it("ignores non-JSON content types", async () => {
    fetchSpy.mockResolvedValueOnce(
      makeResponse({ status: 200, text: "plain", contentType: "text/plain" })
    );
    const out = await api.health();
    expect(out).toBeUndefined();
  });
});

describe("error handling", () => {
  it("throws ApiError with message from JSON detail", async () => {
    fetchSpy.mockResolvedValueOnce(
      makeResponse({ status: 400, json: { detail: "Proxy not found" } })
    );
    await expect(api.proxies.check("ghost")).rejects.toMatchObject({
      status: 400,
      message: "Proxy not found",
    });
  });

  it("falls back to HTTP <status> when JSON has no detail", async () => {
    fetchSpy.mockResolvedValueOnce(
      makeResponse({ status: 500, json: { something: "else" } })
    );
    try {
      await api.dashboard();
      throw new Error("should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).status).toBe(500);
      expect((err as ApiError).message).toBe("HTTP 500");
    }
  });

  it("falls back to text body when JSON parse fails", async () => {
    fetchSpy.mockResolvedValueOnce(
      makeResponse({ status: 502, text: "Bad gateway", contentType: "text/plain" })
    );
    try {
      await api.dashboard();
      throw new Error("should have thrown");
    } catch (err) {
      expect((err as ApiError).status).toBe(502);
      expect((err as ApiError).message).toBe("Bad gateway");
    }
  });

  it("formatApiError explains 405 Method Not Allowed", () => {
    const msg = formatApiError(new ApiError(405, "Method Not Allowed"));
    expect(msg).toContain("405");
    expect(msg).toContain("Создать сессию");
  });

  it("formatApiError explains 401 auth", () => {
    const msg = formatApiError(new ApiError(401, "Missing or invalid Authorization header"));
    expect(msg).toContain("401");
    expect(msg).toContain("ADMIN_TOKEN");
  });

  it("formatApiError keeps specific 401 detail", () => {
    const msg = formatApiError(new ApiError(401, "Неверный текущий пароль"));
    expect(msg).toBe("Неверный текущий пароль");
  });

  it("formatApiError rewrites Firefox NetworkError messages", () => {
    const msg = formatApiError(
      new TypeError("NetworkError when attempting to fetch resource.")
    );
    expect(msg).toMatch(/сеть|соединен/i);
  });

  it("formatApiError explains status 0 upload failures", () => {
    const msg = formatApiError(new ApiError(0, "Сеть оборвала загрузку"));
    expect(msg).toMatch(/сеть|соединен/i);
  });
});

describe("api method routing", () => {
  it.each([
    ["accounts.list", () => api.accounts.list(), "/api/accounts", "GET"],
    [
      "accounts.create",
      () =>
        api.accounts.create({
          username: "u",
          password: "p",
          proxy_label: "x",
        }),
      "/api/accounts",
      "POST",
    ],
    [
      "accounts.pause",
      () => api.accounts.pause("alice"),
      "/api/accounts/alice/pause",
      "POST",
    ],
    [
      "accounts.resume",
      () => api.accounts.resume("alice"),
      "/api/accounts/alice/resume",
      "POST",
    ],
    ["proxies.list", () => api.proxies.list(), "/api/proxies", "GET"],
    [
      "proxies.create",
      () =>
        api.proxies.create({
          label: "x",
          url: "http://h:1",
          skip_health_check: true,
        }),
      "/api/proxies",
      "POST",
    ],
    [
      "proxies.update",
      () =>
        api.proxies.update("p-1", {
          url: "http://new:2",
          skip_health_check: true,
        }),
      "/api/proxies/p-1",
      "PUT",
    ],
    ["proxies.remove", () => api.proxies.remove("p-1"), "/api/proxies/p-1", "DELETE"],
    [
      "proxies.check",
      () => api.proxies.check("p-1"),
      "/api/proxies/p-1/check",
      "POST",
    ],
    ["videos.list", () => api.videos.list(), "/api/videos", "GET"],
    [
      "videos.remove",
      () => api.videos.remove("clip.mp4"),
      "/api/videos/clip.mp4",
      "DELETE",
    ],
    [
      "jobs.enqueue",
      () =>
        api.jobs.enqueue({ username: "u", media_filename: "v.mp4", post_type: "reel" }),
      "/api/jobs",
      "POST",
    ],
    [
      "jobs.cancel",
      () => api.jobs.cancel(7),
      "/api/jobs/7/cancel",
      "POST",
    ],
    ["events.list", () => api.events.list(), "/api/events", "GET"],
    [
      "publications.list",
      () => api.publications.list({ limit: 25 }),
      "/api/publications?limit=25",
      "GET",
    ],
    [
      "publications.refreshStats",
      () => api.publications.refreshStats(9),
      "/api/publications/9/refresh-stats",
      "POST",
    ],
  ])("%s -> %s %s", async (_name, exec, expectedUrl, expectedMethod) => {
    fetchSpy.mockResolvedValueOnce(makeResponse({ json: {} }));
    await exec();
    const { url, init } = getCall();
    expect(url).toBe(expectedUrl);
    expect(init.method ?? "GET").toBe(expectedMethod);
  });
});

describe("URL encoding", () => {
  it("encodes special characters in path params", async () => {
    fetchSpy.mockResolvedValueOnce(makeResponse({ json: {} }));
    await api.accounts.pause("user with space");
    expect(getCall().url).toBe("/api/accounts/user%20with%20space/pause");
  });
});
