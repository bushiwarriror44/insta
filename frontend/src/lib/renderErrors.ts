export const LOCAL_RENDER_HINT_MARKER = "Локальный рендер:";

const LOCAL_HINT =
  "Локальный рендер: в «Администрирование» запустите GPU Salad (Running), в .env задайте WAN_BASE_URL, в «Рендеры» выберите бэкенд local.";

export function withLocalRenderHint(detail: string): string {
  const text = (detail || "").trim();
  if (!text || text.includes(LOCAL_RENDER_HINT_MARKER)) {
    return text || LOCAL_HINT;
  }
  return `${text} — ${LOCAL_HINT}`;
}
