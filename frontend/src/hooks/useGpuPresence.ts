import { useCallback } from "react";

import { api } from "../api/client";
import { usePollWhenVisible } from "./usePollWhenVisible";

const STORAGE_KEY = "insta-gpu-presence-id";
const PING_MS = 45_000;

function clientId(): string {
  try {
    const existing = sessionStorage.getItem(STORAGE_KEY);
    if (existing && existing.length >= 8) return existing;
    const next =
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `tab-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
    sessionStorage.setItem(STORAGE_KEY, next);
    return next;
  } catch {
    return `tab-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  }
}

/** Ping the API while this tab is visible so Salad idle-stop stays off. */
export function useGpuPresence(enabled: boolean) {
  const ping = useCallback(async () => {
    try {
      await api.gpu.presence(clientId());
    } catch {
      /* presence is best-effort; idle loop tolerates gaps within TTL */
    }
  }, []);

  usePollWhenVisible(ping, PING_MS, enabled);
}
