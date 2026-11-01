import type { AccountConnectionTestOut, AccountUserHintOut, FirstLoginOut } from "../api/types";
import type { ToastAction } from "../context/ToastContext";

export const PLAYWRIGHT_INSTALL_HINT =
  "Docker: docker compose exec reels-api python -m app.cli install-playwright";

export type HintActionCallbacks = {
  onOpenSessionSetup?: () => void;
  onOpenSessionBrowser?: () => void;
  onEditAccountEmail?: () => void;
  onAttachProxy?: () => void;
};

type ToastPush = (
  message: string,
  kind?: "success" | "error" | "info",
  action?: ToastAction
) => void;

export function severityToToastKind(
  severity: AccountUserHintOut["severity"]
): "success" | "error" | "info" {
  if (severity === "warn") return "info";
  if (severity === "error") return "error";
  return "info";
}

export function toastFromUserHint(
  hint: AccountUserHintOut,
  push: ToastPush,
  action?: ToastAction
): void {
  const kind = severityToToastKind(hint.severity);
  const text = hint.title ? `${hint.title}: ${hint.message}` : hint.message;
  push(text, kind, action);
}

export function hintActionToToast(
  hint: AccountUserHintOut,
  callbacks: HintActionCallbacks
): ToastAction | undefined {
  const label = hint.action_label?.trim();
  const key = hint.action_key;
  if (!label || !key) return undefined;
  switch (key) {
    case "open_session_setup":
      return callbacks.onOpenSessionSetup
        ? { label, onClick: callbacks.onOpenSessionSetup }
        : undefined;
    case "open_session_browser":
      return callbacks.onOpenSessionBrowser
        ? { label, onClick: callbacks.onOpenSessionBrowser }
        : undefined;
    case "edit_account_email":
      return callbacks.onEditAccountEmail
        ? { label, onClick: callbacks.onEditAccountEmail }
        : undefined;
    case "attach_proxy":
      return callbacks.onAttachProxy ? { label, onClick: callbacks.onAttachProxy } : undefined;
    case "install_playwright":
      return {
        label: label || "Скопировать команду",
        onClick: () => {
          void copyText(PLAYWRIGHT_INSTALL_HINT);
        },
      };
    case "submit_code":
      return callbacks.onOpenSessionBrowser
        ? { label, onClick: callbacks.onOpenSessionBrowser }
        : undefined;
    default:
      return undefined;
  }
}

async function copyText(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    window.prompt("Скопируйте текст:", text);
  }
}

export function pushUserHintToast(
  hint: AccountUserHintOut,
  push: ToastPush,
  callbacks?: HintActionCallbacks,
  overrideAction?: ToastAction
): void {
  const action =
    overrideAction ?? (callbacks ? hintActionToToast(hint, callbacks) : undefined);
  toastFromUserHint(hint, push, action);
}

export function pickUserHint(
  data: FirstLoginOut | AccountConnectionTestOut
): AccountUserHintOut | null {
  return data.user_hint ?? null;
}

export function fallbackFirstLoginHint(data: FirstLoginOut): AccountUserHintOut | null {
  if (data.ok) return null;
  const err = (data.error || "").toLowerCase();
  if (
    data.challenge ||
    data.browser_tab_hint ||
    err.includes("2fa") ||
    err.includes("totp") ||
    err.includes("двухфактор")
  ) {
    const twoFactor =
      err.includes("2fa") || err.includes("totp") || err.includes("двухфактор");
    return {
      severity: twoFactor ? "warn" : "info",
      title: twoFactor ? "Требуется двухфакторная авторизация" : "Нужно подтверждение",
      message: twoFactor
        ? "Завершите вход в Instagram через браузер (2FA) или добавьте секрет TOTP в карточке."
        : "Instagram запросил код из почты, 2FA или проверку.",
      steps: [
        "Нажмите «Открыть браузер» ниже.",
        "В noVNC войдите и сохраните сессию.",
      ],
      action_key: "open_session_browser",
      action_label: "Открыть браузер",
    };
  }
  if (err.includes("поля формы входа")) {
    return {
      severity: "warn",
      title: "Форма входа не найдена",
      message: "Попробуйте вход через браузер или импорт sessionid.",
      steps: ["Вкладка «Через браузер» в этом окне.", "Или вставьте sessionid вручную."],
    };
  }
  if (data.error) {
    return {
      severity: "error",
      title: "Автовход не удался",
      message: "Подробности в логе ниже.",
      steps: ["Смотрите лог ниже."],
    };
  }
  return null;
}

export function fallbackConnectionHint(
  data: AccountConnectionTestOut
): AccountUserHintOut | null {
  if (data.user_hint) return data.user_hint;
  if (data.overall_ok && data.proxy_health?.geo_mismatch) {
    return {
      severity: "warn",
      title: "Гео прокси",
      message: "Страна IP не совпадает с меткой прокси.",
      steps: ["Смените прокси или обновите country в записи прокси."],
    };
  }
  if (data.overall_ok) return null;
  const auth = data.instagram_auth;
  if (auth?.error_code === "session_missing") {
    return {
      severity: "info",
      title: "Нет сессии",
      message: auth.error || "Сессия не настроена.",
      steps: ["Откройте «Настройка сессии» для этого аккаунта."],
    };
  }
  return {
    severity: "error",
    title: "Проверка не пройдена",
    message: auth?.error || "Есть проблемы с подключением.",
    steps: ["Смотрите лог диагностики."],
  };
}

export function resolveFirstLoginHint(data: FirstLoginOut): AccountUserHintOut | null {
  return pickUserHint(data) ?? fallbackFirstLoginHint(data);
}

export function resolveConnectionHint(
  data: AccountConnectionTestOut
): AccountUserHintOut | null {
  return pickUserHint(data) ?? fallbackConnectionHint(data);
}
