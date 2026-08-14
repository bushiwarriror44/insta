import { Copy } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { DiagnosticLogLine } from "../api/types";

const LEVEL_CLASS: Record<DiagnosticLogLine["level"], string> = {
  info: "text-slate-300",
  warn: "text-amber-300",
  error: "text-rose-300",
};

const LEVEL_BADGE_CLASS: Record<DiagnosticLogLine["level"], string> = {
  info: "bg-slate-800 text-slate-400",
  warn: "bg-amber-950/80 text-amber-300",
  error: "bg-rose-950/80 text-rose-300",
};

const STEP_LABELS: Record<string, string> = {
  storage: "Хранилище",
  proxy: "Прокси",
  proxy_health: "Прокси",
  instagram_reach: "Instagram",
  fingerprint: "Отпечаток",
  session_probe: "Сессия",
  session: "Сессия",
  start: "Старт",
  account: "Аккаунт",
  cap: "Лимит",
  media: "Медиа",
  uniquify: "Уникализация",
  caption: "Подпись",
  login: "Вход",
  browser: "Браузер",
  import: "Импорт",
  verify: "Проверка",
  warmup: "Прогрев",
  upload: "Загрузка",
  settling: "Пауза",
  publish: "Публикация",
  done: "Готово",
  timezone: "Часовой пояс",
  fallback: "Fallback",
  mint: "Mint",
  vnc: "VNC",
  goto: "Переход",
  autofill: "Автозаполнение",
  code: "Код",
  save: "Сохранение",
  stop: "Стоп",
  poll: "Опрос",
};

function formatTime(iso: string) {
  try {
    return new Date(iso).toLocaleTimeString("ru-RU");
  } catch {
    return iso;
  }
}

function stepLabel(step: string) {
  return STEP_LABELS[step] ?? step;
}

/** Plain-text dump for clipboard / support pastes. */
export function formatDiagnosticLogPlain(lines: DiagnosticLogLine[]): string {
  return lines
    .map((line) => {
      const level = (line.level || "info").toUpperCase().padEnd(5, " ");
      const step = (line.step || "-").padEnd(14, " ");
      return `[${line.ts}] ${level} ${step} ${line.message}`;
    })
    .join("\n");
}

const CLIPBOARD_API_TIMEOUT_MS = 400;

function copyViaExecCommand(text: string): boolean {
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.style.position = "fixed";
  ta.style.top = "0";
  ta.style.left = "0";
  ta.style.width = "1px";
  ta.style.height = "1px";
  ta.style.padding = "0";
  ta.style.border = "none";
  ta.style.outline = "none";
  ta.style.boxShadow = "none";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.focus();
  ta.select();
  ta.setSelectionRange(0, ta.value.length);
  let ok = false;
  try {
    ok = typeof document.execCommand === "function" && document.execCommand("copy");
  } catch {
    ok = false;
  } finally {
    document.body.removeChild(ta);
  }
  return ok;
}

/** Works on HTTP (non-secure) via textarea fallback when Clipboard API is blocked. */
export async function copyTextToClipboard(text: string): Promise<boolean> {
  const canUseClipboardApi =
    typeof window !== "undefined" &&
    window.isSecureContext &&
    typeof navigator.clipboard?.writeText === "function";

  if (canUseClipboardApi) {
    try {
      await Promise.race([
        navigator.clipboard.writeText(text),
        new Promise<never>((_, reject) =>
          window.setTimeout(() => reject(new Error("clipboard-timeout")), CLIPBOARD_API_TIMEOUT_MS)
        ),
      ]);
      return true;
    } catch {
      /* fall through to execCommand */
    }
  }

  return copyViaExecCommand(text);
}

interface Props {
  lines: DiagnosticLogLine[];
  emptyLabel?: string;
  maxHeightClass?: string;
  autoScroll?: boolean;
}

export function DiagnosticLogPanel({
  lines,
  emptyLabel = "Записей в логе пока нет.",
  maxHeightClass = "max-h-56",
  autoScroll = true,
}: Props) {
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const [copyStatus, setCopyStatus] = useState<"idle" | "ok" | "fail">("idle");

  useEffect(() => {
    if (!autoScroll) return;
    bottomRef.current?.scrollIntoView?.({ behavior: "smooth" });
  }, [lines, autoScroll]);

  useEffect(() => {
    if (copyStatus === "idle") return;
    const t = window.setTimeout(() => setCopyStatus("idle"), 2000);
    return () => window.clearTimeout(t);
  }, [copyStatus]);

  async function copyLog() {
    const text = formatDiagnosticLogPlain(lines);
    const ok = await copyTextToClipboard(text);
    setCopyStatus(ok ? "ok" : "fail");
  }

  if (lines.length === 0) {
    return (
      <div className="rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-4 text-xs text-slate-500">
        {emptyLabel}
      </div>
    );
  }

  const copyLabel =
    copyStatus === "ok"
      ? "Скопировано"
      : copyStatus === "fail"
        ? "Не удалось скопировать"
        : "Копировать";

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/60 overflow-hidden">
      <div className="flex items-center justify-between gap-2 px-3 py-1.5 border-b border-slate-800/80 bg-slate-950/80">
        <span className="text-[10px] font-medium uppercase tracking-wide text-slate-500">Лог</span>
        <button
          type="button"
          className={`btn-ghost text-[11px] py-0.5 px-2 h-auto ${
            copyStatus === "fail" ? "text-rose-300" : ""
          }`}
          onClick={() => void copyLog()}
        >
          <Copy size={12} />
          {copyLabel}
        </button>
      </div>
      <div className={`overflow-y-auto font-mono text-xs ${maxHeightClass}`}>
        <ul className="divide-y divide-slate-800/80">
          {lines.map((line, idx) => (
            <li key={`${line.ts}-${idx}`} className="px-3 py-2 flex gap-2 items-start">
              <span className="text-slate-500 shrink-0 tabular-nums">{formatTime(line.ts)}</span>
              <span
                className={`shrink-0 rounded px-1 py-0.5 text-[10px] uppercase tracking-wide ${LEVEL_BADGE_CLASS[line.level]}`}
              >
                {line.level}
              </span>
              <span className="text-slate-500 shrink-0 w-20 truncate" title={line.step}>
                {stepLabel(line.step)}
              </span>
              <span className={`min-w-0 break-words ${LEVEL_CLASS[line.level]}`}>{line.message}</span>
            </li>
          ))}
        </ul>
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
