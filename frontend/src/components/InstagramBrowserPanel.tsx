import { Loader2, MonitorPlay, Save, Square, Send, CheckCircle2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, formatApiError } from "../api/client";
import type { BrowserSaveOut, BrowserSessionOut, LoginSurface } from "../api/types";
import { useToast } from "../context/ToastContext";

interface Props {
  username: string;
  adminToken?: string | null;
  mode?: "standalone" | "setup";
  loginSurface?: LoginSurface;
  onSessionSaved?: (result: BrowserSaveOut) => void;
}

const POLL_MS = 2500;

function statusLabel(status: BrowserSessionOut["status"]): string {
  switch (status) {
    case "starting":
      return "Запуск…";
    case "running":
      return "Работает";
    case "awaiting_code":
      return "Нужен код";
    case "saved":
      return "Сохранено";
    case "error":
      return "Ошибка";
    default:
      return "Остановлен";
  }
}

export function InstagramBrowserPanel({
  username,
  adminToken,
  mode = "standalone",
  loginSurface = "mobile",
  onSessionSaved,
}: Props) {
  const { push } = useToast();
  const [session, setSession] = useState<BrowserSessionOut | null>(null);
  const [savedOk, setSavedOk] = useState(false);
  const [busy, setBusy] = useState(false);
  const [code, setCode] = useState("");
  const pollRef = useRef<number | null>(null);

  const refreshStatus = useCallback(async () => {
    try {
      const data = await api.accounts.browserStatus(username);
      setSession(data);
    } catch {
      /* ignore transient poll errors */
    }
  }, [username]);

  useEffect(() => {
    setSavedOk(false);
    void refreshStatus();
    pollRef.current = window.setInterval(() => void refreshStatus(), POLL_MS);
    return () => {
      if (pollRef.current !== null) window.clearInterval(pollRef.current);
    };
  }, [refreshStatus, username]);

  const vncUrl = useMemo(() => {
    if (!session?.vnc_path || session.status === "stopped") return null;
    const params = new URLSearchParams({
      autoconnect: "true",
      resize: "scale",
      path: session.vnc_path,
    });
    if (adminToken) {
      params.set("token", adminToken);
      params.set(
        "path",
        `${session.vnc_path}${session.vnc_path.includes("?") ? "&" : "?"}token=${encodeURIComponent(adminToken)}`
      );
    }
    return `/novnc/vnc.html?${params.toString()}`;
  }, [session?.vnc_path, session?.status, adminToken]);

  const active = session && !["stopped", "error"].includes(session.status);
  const isSetup = mode === "setup";

  async function startBrowser() {
    setBusy(true);
    try {
      const data = await api.accounts.browserStart(username, { loginSurface });
      setSession(data);
      setSavedOk(false);
      push("Браузер запущен", "success");
    } catch (err) {
      push(formatApiError(err), "error");
    } finally {
      setBusy(false);
    }
  }

  async function saveSession() {
    setBusy(true);
    try {
      const data = await api.accounts.browserSave(username, { stopAfterSave: false });
      setSession(data);
      if (data.overall_ok) {
        setSavedOk(true);
        onSessionSaved?.(data);
        push("Сессия сохранена и проверена", "success");
      } else {
        setSavedOk(false);
        const err =
          data.connection_test?.instagram_auth.error ?? "Проверка подключения не пройдена";
        push(err, "error");
        onSessionSaved?.(data);
      }
    } catch (err) {
      push(formatApiError(err), "error");
    } finally {
      setBusy(false);
    }
  }

  async function stopBrowser() {
    setBusy(true);
    try {
      const data = await api.accounts.browserStop(username);
      setSession(data);
      push("Браузер остановлен", "success");
    } catch (err) {
      push(formatApiError(err), "error");
    } finally {
      setBusy(false);
    }
  }

  async function submitCode() {
    setBusy(true);
    try {
      const data = await api.accounts.browserSubmitCode(username, code.trim() || null);
      setSession(data);
      setCode("");
      push("Код отправлен", "success");
    } catch (err) {
      push(formatApiError(err), "error");
    } finally {
      setBusy(false);
    }
  }

  const setupStep = savedOk ? 4 : active ? 2 : 1;

  return (
    <div className="space-y-4">
      {isSetup ? (
        <p className="text-xs text-slate-400">
          Браузер открыт в режиме:{" "}
          <span className="text-slate-200">
            {loginSurface === "mobile" ? "Мобильный" : "Десктоп"}
          </span>
        </p>
      ) : null}

      {isSetup ? (
        <ol className="list-decimal list-inside space-y-1 text-sm text-slate-300">
          <li className={setupStep >= 1 ? "text-slate-200" : ""}>
            Запустите браузер и войдите в Instagram через прокси аккаунта
          </li>
          <li className={setupStep >= 2 ? "text-slate-200" : ""}>
            При 2FA/challenge введите код в браузере или в поле слева
          </li>
          <li className={setupStep >= 3 ? "text-slate-200" : ""}>
            <strong>Сохраните сессию</strong> — обязательный шаг перед завершением настройки
          </li>
          <li className={setupStep >= 4 ? "text-emerald-300" : ""}>
            Остановите браузер — сессия останется в БД для автопостинга
          </li>
        </ol>
      ) : null}

      <div className="rounded-xl border border-rose-500/30 bg-rose-950/20 p-3 text-xs text-rose-100">
        VNC даёт полный доступ к экрану сервера, включая пароль в браузере. Используйте только
        на доверенной сети и с ADMIN_TOKEN.
      </div>

      {savedOk ? (
        <div className="rounded-lg border border-emerald-700/50 bg-emerald-950/30 p-3 text-sm text-emerald-200 flex items-center gap-2">
          <CheckCircle2 size={16} />
          Сессия сохранена — можно остановить браузер и нажать «Готово» в модале
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className="btn-primary" disabled={busy || !!active} onClick={startBrowser}>
          <MonitorPlay size={16} className={busy ? "animate-spin" : ""} />
          Запустить браузер
        </button>
        <button type="button" className="btn-ghost" disabled={busy || !active || savedOk} onClick={saveSession}>
          <Save size={16} />
          Сохранить сессию
        </button>
        <button type="button" className="btn-ghost" disabled={busy || !active} onClick={stopBrowser}>
          <Square size={16} />
          Остановить
        </button>
        {session ? (
          <span className="text-xs text-slate-400 ml-auto">
            Статус: <span className="text-slate-200">{statusLabel(session.status)}</span>
            {session.awaiting_code ? " · введите 2FA" : null}
          </span>
        ) : (
          <Loader2 size={16} className="animate-spin text-slate-500 ml-auto" />
        )}
      </div>

      <div className="grid gap-3 md:grid-cols-[220px_1fr]">
        <div className="space-y-2">
          <label className="label" htmlFor={`browser-code-${username}`}>
            Код подтверждения
          </label>
          <input
            id={`browser-code-${username}`}
            className="input font-mono text-sm"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="2FA / challenge / backup"
            autoComplete="one-time-code"
          />
          <button
            type="button"
            className="btn-ghost w-full"
            disabled={busy || !active}
            onClick={submitCode}
          >
            <Send size={14} />
            Отправить
          </button>
          <p className="text-xs text-slate-500">
            Введите код здесь или прямо в окне браузера справа.
          </p>
        </div>

        <div className="rounded-lg border border-slate-700 bg-black/40 overflow-hidden min-h-[360px]">
          {vncUrl ? (
            <iframe
              title={`Instagram browser ${username}`}
              src={vncUrl}
              className="w-full h-[600px] bg-black"
              allow="clipboard-read; clipboard-write"
            />
          ) : (
            <div className="flex h-[360px] items-center justify-center text-sm text-slate-500">
              Запустите браузер, чтобы увидеть Instagram через noVNC
            </div>
          )}
        </div>
      </div>

      {session?.page_url ? (
        <p className="text-xs text-slate-500 truncate">URL: {session.page_url}</p>
      ) : null}
      {session?.error ? <p className="text-xs text-rose-300">{session.error}</p> : null}
    </div>
  );
}
