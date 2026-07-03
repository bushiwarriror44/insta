import { API_BASE, getAuthHeaders } from "./client";

export function mediaApiPath(filename: string): string {
  return `${API_BASE}/api/videos/${encodeURIComponent(filename)}`;
}

export async function fetchMediaObjectUrl(
  filename: string,
  signal?: AbortSignal
): Promise<string> {
  const res = await fetch(mediaApiPath(filename), {
    headers: getAuthHeaders(),
    signal,
  });
  if (!res.ok) {
    throw new Error(`Failed to load media: HTTP ${res.status}`);
  }
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}

export function revokeMediaObjectUrl(url: string | null | undefined): void {
  if (url) URL.revokeObjectURL(url);
}

export function formatDuration(sec: number | null | undefined): string {
  if (sec == null || !Number.isFinite(sec) || sec <= 0) return "";
  const total = Math.round(sec);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
