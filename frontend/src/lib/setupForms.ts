import type { AskField } from "../api/assistant";

/** Mirrors app/assistant/setup_fields.py — keep ids in sync. */
export const ACCOUNT_FORM_FIELDS: AskField[] = [
  { id: "proxy_label", label: "Метка прокси", kind: "text", required: true },
  { id: "username", label: "Username", kind: "text", required: true },
  {
    id: "platform",
    label: "Площадка",
    kind: "select",
    options: ["instagram", "youtube", "tiktok"],
    required: true,
  },
  { id: "password", label: "Пароль Instagram", kind: "password", required: true },
  { id: "email", label: "Email", kind: "text", required: false },
  { id: "email_password", label: "Пароль email", kind: "password", required: false },
  { id: "imap_host", label: "IMAP хост (если не авто)", kind: "text", required: false },
  { id: "login_identifier", label: "Логин (email/телефон)", kind: "text", required: false },
  { id: "vendor_line", label: "Строка продавца (tab)", kind: "text", required: false },
  { id: "totp_seed", label: "TOTP seed", kind: "password", required: false },
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

export function fieldIsRequired(field: AskField): boolean {
  return field.required !== false;
}

export function askFormIncomplete(fields: AskField[], answers: Record<string, string>): boolean {
  return fields.some((field) => fieldIsRequired(field) && !(answers[field.id] ?? "").trim());
}
