import { CheckCircle2, Eye, EyeOff, Loader2, MonitorPlay, Save, Send, Square } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, formatApiError } from "../api/client";
import type { BrowserSaveOut, BrowserSessionOut, LoginSurface } from "../api/types";
import { useToast } from "../context/ToastContext";
import { CountryFlag } from "./CountryFlag";

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
  const [notesDraft, setNotesDraft] = useState("");
  const [showPassword, setShowPassword] = useState(false);
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

  useEffect(() => {
    setNotesDraft(session?.account_notes ?? "");
  }, [session?.account_notes]);

  const vncPath = session?.vnc_path?.replace(/^\//, "") ?? "";

  const vncUrl = useMemo(() => {
    if (!vncPath || session?.status === "stopped") return null;
    const params = new URLSearchParams({
      autoconnect: "true",
      resize: "scale",
      path: vncPath,
      quality: "6",
      compression: "2",
    });
    if (adminToken) {
      params.set("token", adminToken);
      params.set(
        "path",
        `${vncPath}${vncPath.includes("?") ? "&" : "?"}token=${encodeURIComponent(adminToken)}`
      );
    }
    return `/novnc/vnc.html?${params.toString()}`;
  }, [vncPath, session?.status, adminToken]);

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

  async function openInstagram() {
    setBusy(true);
    try {
      const data = await api.accounts.browserOpenInstagram(username);
      setSession(data);
      push("Запрос на открытие Instagram отправлен", "success");
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
        push("Сессия сохранена", "success");
      } else {
        setSavedOk(false);
        const err =
          data.logs?.find((l) => l.level === "error")?.message ??
          "Не удалось сохранить sessionid из браузера";
        push(err, "error");
        onSessionSaved?.(data);
      }
    } catch (err) {
      push(formatApiError(err), "error");
    } finally {
      setBusy(false);
    }
  }

  async function saveNotes() {
    setBusy(true);
    try {
      await api.accounts.updateNotes(username, {
        notes: notesDraft.trim() ? notesDraft.trim() : null,
      });
      setSession((prev) => (prev ? { ...prev, account_notes: notesDraft.trim() || null } : prev));
      push("Заметки сохранены", "success");
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
          {loginSurface === "mobile" ? (
            <span className="block mt-1 text-slate-500">
              На VPS 1 GB режим <strong className="text-slate-400">Десктоп</strong> обычно
              отзывчивее.
            </span>
          ) : null}
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

      {session?.status === "running" &&
      (session.warning?.includes("без автозахода") ||
        session.page_url === "about:blank" ||
        session.page_url?.startsWith("chrome://")) ? (
        <div className="rounded-lg border border-sky-500/30 bg-sky-950/20 p-3 text-sm text-sky-100">
          Instagram не открывается автоматически — так меньше шанс HTTP 429. Когда будете готовы,
          нажмите «Открыть Instagram» или введите адрес вручную в окне VNC.
        </div>
      ) : null}

      {session?.status === "running" && session.warning ? (
        <div className="rounded-lg border border-amber-500/40 bg-amber-950/30 p-3 text-sm text-amber-100">
          {session.warning.includes("429") || session.proxy_instagram_login_http_status === 429 ? (
            <>
              Instagram временно ограничил запросы с IP прокси{" "}
              <span className="font-mono">{session.proxy_ip ?? ""}</span> (HTTP 429). Это лимит
              по IP, а не детект автоматизации — эмуляция телефона здесь не помогает. Подождите
              30–60 минут, не нажимайте Reload в браузере, или смените прокси на другой IP.
            </>
          ) : (
            <>
              Браузер запущен, но Instagram не загрузился автоматически — откройте вручную в окне
              справа. {session.warning}
            </>
          )}
          {session.page_url === "about:blank" &&
          !session.warning.includes("429") &&
          session.proxy_instagram_login_http_status !== 429 ? (
            <span className="block mt-1 text-amber-200/90">
              Попробуйте ввести <span className="font-mono">instagram.com</span> в адресной строке
              Chromium внутри окна noVNC.
            </span>
          ) : null}
        </div>
      ) : null}

      {session?.account_username ? (
        <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-3 text-sm text-slate-300 space-y-2">
          <p className="text-xs uppercase tracking-wide text-slate-500">Аккаунт</p>
          <p>
            <span className="text-slate-400">Username:</span>{" "}
            <span className="text-slate-100 font-mono">@{session.account_username}</span>
          </p>
          <p>
            <span className="text-slate-400">Логин для Instagram:</span>{" "}
            <span className="text-slate-100 font-mono">{session.account_login ?? "—"}</span>
            {session.account_login &&
            session.account_username &&
            session.account_login !== session.account_username ? (
              <span className="text-slate-500 text-xs ml-1">(отличается от username)</span>
            ) : null}
          </p>
          <p className="flex flex-wrap items-center gap-2">
            <span className="text-slate-400">Пароль:</span>
            <span className="text-slate-100 font-mono">
              {showPassword ? session.account_password ?? "—" : "••••••••"}
            </span>
            {session.account_password ? (
              <button
                type="button"
                className="btn-ghost px-2 py-1 text-xs"
                onClick={() => setShowPassword((v) => !v)}
                aria-label={showPassword ? "Скрыть пароль" : "Показать пароль"}
              >
                {showPassword ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            ) : null}
          </p>
          <div className="space-y-1">
            <label className="text-slate-400 text-xs" htmlFor={`account-notes-${username}`}>
              Заметки
            </label>
            <textarea
              id={`account-notes-${username}`}
              className="input min-h-[72px] text-sm w-full"
              value={notesDraft}
              onChange={(e) => setNotesDraft(e.target.value)}
              placeholder="Заметки администратора по этому аккаунту"
            />
            <button
              type="button"
              className="btn-ghost text-xs"
              disabled={busy}
              onClick={() => void saveNotes()}
            >
              Сохранить заметки
            </button>
          </div>
        </div>
      ) : null}

      {session?.proxy_label ? (
        <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-3 text-sm text-slate-300 space-y-1">
          <p className="text-xs uppercase tracking-wide text-slate-500">Прокси сессии</p>
          <p>
            <span className="text-slate-400">Прокси:</span>{" "}
            <span className="text-slate-100 font-mono">{session.proxy_label}</span>
          </p>
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span>
              <span className="text-slate-400">IP:</span>{" "}
              <span className="text-slate-100 font-mono">{session.proxy_ip ?? "—"}</span>
            </span>
            <span className="inline-flex items-center gap-1">
              <span className="text-slate-400">Гео:</span>
              <CountryFlag code={session.proxy_geo_country} showCode />
            </span>
            {session.proxy_country ? (
              <span className="inline-flex items-center gap-1">
                <span className="text-slate-400">Задано:</span>
                <CountryFlag code={session.proxy_country} showCode />
              </span>
            ) : null}
            <span>
              <span className="text-slate-400">Таймзона:</span>{" "}
              <span className="text-slate-100 font-mono">{session.proxy_timezone ?? "—"}</span>
            </span>
            {session.proxy_instagram_reachable != null ? (
              <span
                className={
                  session.proxy_instagram_reachable ? "text-emerald-300" : "text-rose-300"
                }
              >
                Instagram API: {session.proxy_instagram_reachable ? "доступен" : "недоступен"}
              </span>
            ) : null}
            {session.proxy_instagram_login_reachable != null ? (
              <span
                className={
                  session.proxy_instagram_login_reachable ? "text-emerald-300" : "text-rose-300"
                }
              >
                Страница логина:{" "}
                {session.proxy_instagram_login_reachable ? "доступна" : "недоступна"}
                {session.proxy_instagram_login_http_status
                  ? ` (HTTP ${session.proxy_instagram_login_http_status})`
                  : null}
              </span>
            ) : null}
          </p>
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className="btn-primary" disabled={busy || !!active} onClick={startBrowser}>
          <MonitorPlay size={16} className={busy ? "animate-spin" : ""} />
          Запустить браузер
        </button>
        <button
          type="button"
          className="btn-ghost"
          disabled={busy || !active}
          onClick={openInstagram}
        >
          Открыть Instagram
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
          {active && vncUrl ? (
            <p className="px-3 py-2 text-xs text-slate-500 border-b border-slate-800">
              Если noVNC пишет «Failed to connect» — на VPS в <span className="font-mono">/etc/nginx/sites-available/insta</span>{" "}
              нужны заголовки WebSocket Upgrade (см. <span className="font-mono">deploy/host-nginx.conf.example</span>
              ), затем <span className="font-mono">nginx -t && systemctl reload nginx</span>.
            </p>
          ) : null}
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
