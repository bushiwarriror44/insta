import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../../api/client";
import { useGpuPresence } from "../useGpuPresence";

vi.mock("../../api/client", () => ({
  api: {
    gpu: {
      presence: vi.fn().mockResolvedValue({ ok: true, viewers: 1 }),
    },
  },
}));

beforeEach(() => {
  sessionStorage.clear();
  vi.mocked(api.gpu.presence).mockClear();
  vi.mocked(api.gpu.presence).mockResolvedValue({ ok: true, viewers: 1 });
});

describe("useGpuPresence", () => {
  it("pings presence when enabled and the tab is visible", async () => {
    Object.defineProperty(document, "hidden", { configurable: true, get: () => false });
    renderHook(() => useGpuPresence(true));
    await waitFor(() => expect(api.gpu.presence).toHaveBeenCalled());
    const clientId = vi.mocked(api.gpu.presence).mock.calls[0][0];
    expect(clientId.length).toBeGreaterThanOrEqual(8);
    expect(sessionStorage.getItem("insta-gpu-presence-id")).toBe(clientId);
  });

  it("does not ping when disabled", async () => {
    renderHook(() => useGpuPresence(false));
    await new Promise((r) => setTimeout(r, 30));
    expect(api.gpu.presence).not.toHaveBeenCalled();
  });
});
