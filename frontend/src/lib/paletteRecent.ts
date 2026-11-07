const RECENT_KEY = "palette:recent";
const RECENT_MAX = 5;

export type PaletteRecentEntry = { to: string; label: string };

export function readPaletteRecent(): PaletteRecentEntry[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(RECENT_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((item): item is PaletteRecentEntry => {
        if (!item || typeof item !== "object") return false;
        const row = item as Record<string, unknown>;
        return typeof row.to === "string" && typeof row.label === "string";
      })
      .slice(0, RECENT_MAX);
  } catch {
    return [];
  }
}

export function pushPaletteRecent(entry: PaletteRecentEntry) {
  if (typeof window === "undefined") return;
  const next = [entry, ...readPaletteRecent().filter((item) => item.to !== entry.to)].slice(0, RECENT_MAX);
  try {
    window.localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    /* ignore quota */
  }
}
