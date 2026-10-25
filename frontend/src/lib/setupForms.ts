import type { AskField, AskOption } from "../api/assistant";

export type FormKind = "account" | "proxy" | "publish";

/** Mirrors app/assistant/setup_fields.py — keep ids in sync. */
export const ACCOUNT_FORM_FIELDS: AskField[] = [
  { id: "proxy_label", label: "Метка прокси", kind: "text", required: true },
  { id: "username", label: "Имя пользователя", kind: "text", required: true },
  {
    id: "platform",
    label: "Площадка",
    kind: "select",
    options: ["instagram", "youtube", "tiktok"],
    required: true,
  },
  { id: "password", label: "Пароль Instagram", kind: "password", required: false },
  { id: "email", label: "Эл. почта", kind: "text", required: false },
  { id: "email_password", label: "Пароль email", kind: "password", required: false },
  { id: "imap_host", label: "IMAP хост (если не авто)", kind: "text", required: false },
  { id: "login_identifier", label: "Логин (email/телефон)", kind: "text", required: false },
  { id: "vendor_line", label: "Строка продавца (tab)", kind: "text", required: false },
  { id: "totp_seed", label: "Секрет TOTP", kind: "password", required: false },
];

export const PROXY_FORM_FIELDS: AskField[] = [
  { id: "label", label: "Метка прокси", kind: "text", required: true },
  {
    id: "url",
    label: "URL (http://user:pass@host:port)",
    kind: "password",
    required: true,
  },
  { id: "country", label: "Страна", kind: "text", required: false },
];

export const PUBLISH_FORM_FIELDS: AskField[] = [
  { id: "account_id", label: "Аккаунт", kind: "select", required: true },
  { id: "filename", label: "Файл из библиотеки", kind: "select", required: true },
  { id: "title", label: "Заголовок", kind: "text", required: false },
  { id: "caption", label: "Подпись / caption", kind: "text", required: false },
  { id: "description", label: "Описание (YouTube)", kind: "text", required: false },
  { id: "tags", label: "Теги", kind: "text", required: false },
  {
    id: "when",
    label: "Когда (ISO или пусто = сейчас)",
    kind: "text",
    required: false,
  },
  {
    id: "post_type",
    label: "Тип поста",
    kind: "select",
    options: ["reel", "youtube_short", "tiktok"],
    required: false,
  },
];

export function optionValue(option: AskOption): string {
  return typeof option === "string" ? option : option.value;
}

export function optionLabel(option: AskOption): string {
  return typeof option === "string" ? option : option.label;
}

export function detectFormKind(
  fields: AskField[] | null | undefined,
  explicit?: string | null
): FormKind | null {
  const raw = (explicit || "").trim().toLowerCase();
  if (raw === "account" || raw === "proxy" || raw === "publish") return raw;
  const ids = new Set((fields ?? []).map((field) => field.id));
  if (ids.has("account_id") && ids.has("filename")) return "publish";
  if (ids.has("proxy_label") && ids.has("username") && ids.has("platform")) return "account";
  if (ids.has("label") && ids.has("url") && !ids.has("username") && !ids.has("proxy_label")) {
    return "proxy";
  }
  return null;
}

export function fieldIsRequired(field: AskField, answers: Record<string, string> = {}): boolean {
  if (field.id === "password") {
    const platform = (answers.platform ?? "").trim();
    return platform === "" || platform === "instagram";
  }
  return field.required !== false;
}

export function askFormIncomplete(fields: AskField[], answers: Record<string, string>): boolean {
  return fields.some((field) => fieldIsRequired(field, answers) && !(answers[field.id] ?? "").trim());
}

export function withFieldOptions(
  fields: AskField[],
  updates: Record<string, AskOption[]>
): AskField[] {
  return fields.map((field) => {
    const next = updates[field.id];
    if (!next) return field;
    return { ...field, options: next, kind: field.kind ?? "select" };
  });
}
