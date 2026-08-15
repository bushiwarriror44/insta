import { act, render, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api/client";
import { AuthProvider, useAuth } from "../AuthContext";

const healthMock = vi.hoisted(() => vi.fn());
const dashboardMock = vi.hoisted(() => vi.fn());
const meMock = vi.hoisted(() => vi.fn());

vi.mock("../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../api/client")>(
    "../../api/client"
  );
  return {
    ...actual,
    api: {
      health: healthMock,
      dashboard: dashboardMock,
      auth: { me: meMock },
    },
    configureAuth: vi.fn(),
  };
});

const STORAGE_KEY = "reels-admin-token";

function wrapper({ children }: { children: React.ReactNode }) {
  return <AuthProvider>{children}</AuthProvider>;
}

beforeEach(() => {
  healthMock.mockReset();
  dashboardMock.mockReset();
  meMock.mockReset();
  meMock.mockResolvedValue({ role: "owner", label: "master" });
  window.localStorage.clear();
});

describe("AuthContext", () => {
  it("starts in 'loading' and resolves to 'open' when auth is not required", async () => {
    healthMock.mockResolvedValue({ ok: true, version: "x", auth_required: false });
    const { result } = renderHook(() => useAuth(), { wrapper });
    expect(result.current.state.state).toBe("loading");
    await waitFor(() => expect(result.current.state.state).toBe("open"));
    expect(result.current.authRequired).toBe(false);
  });

  it("resolves to 'needs-login' when no token stored", async () => {
    healthMock.mockResolvedValue({ ok: true, version: "x", auth_required: true });
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.state.state).toBe("needs-login"));
    expect(result.current.authRequired).toBe(true);
  });

  it("resolves to 'authed' when stored token is valid", async () => {
    window.localStorage.setItem(STORAGE_KEY, "stored-token");
    healthMock.mockResolvedValue({ ok: true, version: "x", auth_required: true });
    dashboardMock.mockResolvedValue({});
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.state.state).toBe("authed"));
    if (result.current.state.state === "authed") {
      expect(result.current.state.token).toBe("stored-token");
    }
  });

  it("clears token on 401 from initial dashboard probe", async () => {
    window.localStorage.setItem(STORAGE_KEY, "bad-token");
    healthMock.mockResolvedValue({ ok: true, version: "x", auth_required: true });
    dashboardMock.mockRejectedValue(new ApiError(401, "unauthorized"));
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.state.state).toBe("needs-login"));
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it("resolves to 'error' when health probe throws", async () => {
    healthMock.mockRejectedValue(new Error("network down"));
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.state.state).toBe("error"));
    if (result.current.state.state === "error") {
      expect(result.current.state.message).toBeTruthy();
    }
  });

  it("retryBootstrap re-runs health and can recover from error", async () => {
    healthMock.mockRejectedValueOnce(new Error("network down"));
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.state.state).toBe("error"));

    healthMock.mockResolvedValue({ ok: true, version: "x", auth_required: false });
    act(() => {
      result.current.retryBootstrap();
    });
    await waitFor(() => expect(result.current.state.state).toBe("open"));
  });

  it("login() succeeds and stores token in localStorage", async () => {
    healthMock.mockResolvedValue({ ok: true, version: "x", auth_required: true });
    dashboardMock.mockResolvedValueOnce({});
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.state.state).toBe("needs-login"));

    dashboardMock.mockResolvedValueOnce({});
    let out: Awaited<ReturnType<typeof result.current.login>> | undefined;
    await act(async () => {
      out = await result.current.login("new-token");
    });
    expect(out).toEqual({ ok: true });
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("new-token");
    expect(result.current.state.state).toBe("authed");
  });

  it("login() returns invalid when probe rejects with 401", async () => {
    healthMock.mockResolvedValue({ ok: true, version: "x", auth_required: true });
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.state.state).toBe("needs-login"));

    dashboardMock.mockRejectedValueOnce(new ApiError(401, "nope"));
    let out: Awaited<ReturnType<typeof result.current.login>> | undefined;
    await act(async () => {
      out = await result.current.login("wrong");
    });
    expect(out).toEqual({
      ok: false,
      reason: "invalid",
      message: "Неверный пароль",
    });
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
    expect(result.current.state.state).toBe("needs-login");
  });

  it("login() returns network when probe rejects with non-401", async () => {
    healthMock.mockResolvedValue({ ok: true, version: "x", auth_required: true });
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.state.state).toBe("needs-login"));

    dashboardMock.mockRejectedValueOnce(new ApiError(503, "upstream down"));
    let out: Awaited<ReturnType<typeof result.current.login>> | undefined;
    await act(async () => {
      out = await result.current.login("tok");
    });
    expect(out?.ok).toBe(false);
    if (out && !out.ok) {
      expect(out.reason).toBe("network");
      expect(out.message).toContain("upstream down");
    }
  });

  it("logout() clears token and switches to 'needs-login'", async () => {
    window.localStorage.setItem(STORAGE_KEY, "stored");
    healthMock.mockResolvedValue({ ok: true, version: "x", auth_required: true });
    dashboardMock.mockResolvedValue({});
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.state.state).toBe("authed"));

    act(() => {
      result.current.logout();
    });
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
    expect(result.current.state.state).toBe("needs-login");
  });

  it("useAuth throws when used outside provider", () => {
    function Probe() {
      useAuth();
      return null;
    }
    const orig = console.error;
    console.error = () => {};
    try {
      expect(() => render(<Probe />)).toThrow(/useAuth outside AuthProvider/);
    } finally {
      console.error = orig;
    }
  });
});
