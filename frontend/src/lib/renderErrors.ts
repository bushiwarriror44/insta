export const LOCAL_RENDER_HINT_MARKER = "Локальный рендер:";

const LOCAL_HINT =
  "Локальный рендер: в «Администрирование» запустите GPU Salad (статус «Работает»), в .env задайте WAN_BASE_URL, в «Рендеры» выберите бэкенд local.";

function skipLocalUrlHint(detail: string): boolean {
  const text = detail.toLowerCase();
  return (
    text.includes("таймаут ожидания wan") ||
    text.includes("524") ||
    text.includes("general timeout") ||
    text.includes("не дождался")
  );
}

export function withLocalRenderHint(detail: string): string {
  const text = (detail || "").trim();
  if (!text || text.includes(LOCAL_RENDER_HINT_MARKER)) {
    return text || LOCAL_HINT;
  }
  if (skipLocalUrlHint(text)) {
    return text;
  }
  return `${text} — ${LOCAL_HINT}`;
}
