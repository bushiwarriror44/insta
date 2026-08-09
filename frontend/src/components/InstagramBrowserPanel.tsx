import { CheckCircle2, Copy, Eye, EyeOff, Loader2, MonitorPlay, Save, Send, Square } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, formatApiError } from "../api/client";
import type { BrowserSaveOut, BrowserSessionOut, DiagnosticLogLine, LoginSurface } from "../api/types";
import { useToast } from "../context/ToastContext";
import { CountryFlag } from "./CountryFlag";
import {
  DiagnosticLogPanel,
  copyTextToClipboard,
  formatDiagnosticLogPlain,
} from "./DiagnosticLogPanel";

type BrowserNavTarget =
  | "auto"
  | "login"
  | "home"
  | "reels"
  | "explore"
  | "direct"
  | "activity"
  | "profile"
  | "edit_profile";

const QUICK_NAV: { target: BrowserNavTarget; label: string }[] = [
  { target: "home", label: "Лента" },
  { target: "reels", label: "Reels" },
  { target: "explore", label: "Explore" },
  { target: "direct", label: "Direct" },
  { target: "activity", label: "Активность" },
  { target: "profile", label: "Профиль" },
  { target: "edit_profile", label: "Ред. профиль" },
  { target: "login", label: "Login" },
];

interface Props {
  username: string;
  adminToken?: string | null;
  mode?: "standalone" | "setup";
  loginSurface?: LoginSurface;
  onSessionSaved?: (result: BrowserSaveOut) => void;
}

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

function mergeLogs(prev: DiagnosticLogLine[], next: DiagnosticLogLine[] | undefined): DiagnosticLogLine[] {
  if (!next?.length) return prev;
  const key = (l: DiagnosticLogLine) => `${l.ts}|${l.level}|${l.step}|${l.message}`;
  const seen = new Set(prev.map(key));
  const out = [...prev];
  for (const line of next) {
    const k = key(line);
    if (seen.has(k)) continue;
    seen.add(k);
    out.push(line);
  }
  return out.slice(-300);
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
  const [logs, setLogs] = useState<DiagnosticLogLine[]>([]);
  const [savedOk, setSavedOk] = useState(false);
  const [busy, setBusy] = useState(false);
  const [code, setCode] = useState("");
  const [notesDraft, setNotesDraft] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [copyOk, setCopyOk] = useState(false);
  const pollRef = useRef<number | null>(null);

  const applySession = useCallback((data: BrowserSessionOut) => {
    setSession(data);
    setLogs((prev) => mergeLogs(prev, data.logs));
  }, []);

  const refreshStatus = useCallback(async () => {
    try {
      const data = await api.accounts.browserStatus(username);
      applySession(data);
    } catch {
      /* ignore transient poll errors */
    }
  }, [username, applySession]);

  useEffect(() => {
    setSavedOk(false);
    setLogs([]);
    void refreshStatus();
  }, [refreshStatus, username]);

  useEffect(() => {
    if (pollRef.current !== null) window.clearInterval(pollRef.current);
    const ms = session?.status === "starting" ? 1000 : 2000;
    pollRef.current = window.setInterval(() => void refreshStatus(), ms);
    return () => {
      if (pollRef.current !== null) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [refreshStatus, session?.status]);

  useEffect(() => {
    setNotesDraft(session?.account_notes ?? "");
  }, [session?.account_notes]);

  const vncPath = session?.vnc_path?.replace(/^\//, "") ?? "";

  const vncUrl = useMemo(() => {
    if (!vncPath || !session || ["stopped", "error"].includes(session.status)) return null;
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
  }, [vncPath, session, adminToken]);

  const live =
    !!session && ["running", "awaiting_code", "saved", "starting"].includes(session.status);
  const navReady =
    !!session && ["running", "awaiting_code", "saved"].includes(session.status);
  const isSetup = mode === "setup";
  const showBlankWarning =
    session?.status === "running" &&
    Boolean(
      session.warning ||
        session.page_url === "about:blank" ||
        session.page_url?.startsWith("chrome://") ||
        session.page_url?.startsWith("chrome-error://")
    );

  async function startBrowser() {
    setBusy(true);
    try {
      const data = await api.accounts.browserStart(username, { loginSurface });
      applySession(data);
      setSavedOk(false);
      push("Браузер запущен", "success");
    } catch (err) {
      push(formatApiError(err), "error");
    } finally {
      setBusy(false);
    }
  }

  async function openInstagram(opts?: {
    autofill?: boolean;
    target?: BrowserNavTarget;
  }) {
    setBusy(true);
    try {
      const data = await api.accounts.browserOpenInstagram(username, opts);
      applySession(data);
      const labels: Record<string, string> = {
        home: "Переход на ленту",
        reels: "Переход на Reels",
        explore: "Переход на Explore",
        direct: "Переход в Direct",
        activity: "Переход в Активность",
        profile: "Переход в профиль",
        edit_profile: "Переход в редактирование профиля",
        login: opts?.autofill ? "Login + автозаполнение" : "Переход на Login",
        auto: "Открытие Instagram",
      };
      push(labels[opts?.target ?? "auto"] ?? "Запрос на открытие Instagram отправлен", "success");
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
      applySession(data);
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
      applySession(data);
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
      applySession(data);
      setCode("");
      push("Код отправлен", "success");
    } catch (err) {
      push(formatApiError(err), "error");
    } finally {
      setBusy(false);
    }
  }

  async function copyLogs() {
    const ok = await copyTextToClipboard(formatDiagnosticLogPlain(logs));
    setCopyOk(ok);
    push(ok ? "Лог скопирован" : "Не удалось скопировать лог", ok ? "success" : "error");
    if (ok) window.setTimeout(() => setCopyOk(false), 2000);
  }

  async function copyPageUrl() {
    if (!session?.page_url) return;
    const ok = await copyTextToClipboard(session.page_url);
    push(ok ? "URL скопирован" : "Не удалось скопировать URL", ok ? "success" : "error");
  }

  const setupStep = savedOk ? 4 : live ? 2 : 1;

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
            Запустите браузер — Instagram откроется автоматически через прокси аккаунта
          </li>
          <li className={setupStep >= 2 ? "text-slate-200" : ""}>
            При 2FA/challenge введите код в браузере или в поле слева
          </li>
          <li className={setupStep >= 3 || (live && !savedOk) ? "text-slate-200" : ""}>
            <strong>Сохраните сессию</strong> — обязательный шаг перед завершением настройки
          </li>
          <li className={setupStep >= 4 ? "text-emerald-300" : ""}>
            Остановите браузер — web-cookie останется в БД; для автопостинга сделайте mint
          </li>
        </ol>
      ) : null}

      <div className="rounded-xl border border-rose-500/30 bg-rose-950/20 p-3 text-xs text-rose-100">
        VNC даёт полный доступ к экрану сервера, включая пароль в браузере. Используйте только
        на доверенной сети и с ADMIN_TOKEN.
      </div>

      {savedOk ? (
        <div className="rounded-lg border border-emerald-700/50 bg-emerald-950/30 p-3 text-sm text-emerald-200 space-y-1">
          <div className="flex items-center gap-2">
            <CheckCircle2 size={16} />
            Web-сессия сохранена (sessionid в БД)
          </div>
          <p className="text-xs text-emerald-100/90">
            Это web-cookie. Для стабильного автопостинга один раз нажмите «Подготовить к
            автопостингу» или поставьте пост в очередь — вход пойдёт по паролю и создаст mobile
            dump.
          </p>
        </div>
      ) : null}

      {showBlankWarning && session?.warning ? (
        <div className="rounded-lg border border-amber-500/40 bg-amber-950/30 p-3 text-sm text-amber-100">
          {session.warning.includes("429") || session.proxy_instagram_login_http_status === 429 ? (
            <>
              Instagram временно ограничил запросы с IP прокси{" "}
              <span className="font-mono">{session.proxy_ip ?? ""}</span> (HTTP 429). Подождите
              30–60 минут или смените прокси, затем нажмите «Открыть Instagram».
            </>
          ) : (
            <>
              Автопереход не удался — повторите «Открыть Instagram» / «Login» или введите адрес в
              VNC. {session.warning}
            </>
          )}
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
        <button type="button" className="btn-primary" disabled={busy || live} onClick={startBrowser}>
          <MonitorPlay size={16} className={busy ? "animate-spin" : ""} />
          Запустить браузер
        </button>
        <button
          type="button"
          className="btn-ghost"
          disabled={busy || !navReady}
          onClick={() => void openInstagram({ target: "auto" })}
        >
          Открыть Instagram
        </button>
        <button
          type="button"
          className="btn-ghost text-xs"
          disabled={busy || !navReady}
          onClick={() => void openInstagram({ target: "login", autofill: true })}
        >
          Заполнить логин
        </button>
        <button type="button" className="btn-ghost" disabled={busy || !navReady || savedOk} onClick={saveSession}>
          <Save size={16} />
          Сохранить сессию
        </button>
        <button type="button" className="btn-ghost" disabled={busy || !live} onClick={stopBrowser}>
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

      <div className="rounded-lg border border-slate-700 bg-slate-900/40 p-3 space-y-2">
        <p className="text-xs uppercase tracking-wide text-slate-500">Быстрый переход в Instagram</p>
        <div className="flex flex-wrap gap-2">
          {QUICK_NAV.map((item) => (
            <button
              key={item.target}
              type="button"
              className="btn-ghost text-xs"
              disabled={busy || !navReady}
              onClick={() => void openInstagram({ target: item.target })}
            >
              {item.label}
            </button>
          ))}
        </div>
        <p className="text-xs text-slate-500">
          Страница откроется внутри noVNC-браузера через прокси аккаунта.
        </p>
      </div>

      <div className="rounded-lg border border-slate-700 bg-slate-900/40 p-3 space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs uppercase tracking-wide text-slate-500">Текущая страница</p>
          <button
            type="button"
            className="btn-ghost text-xs"
            disabled={!session?.page_url}
            onClick={() => void copyPageUrl()}
          >
            <Copy size={12} />
            Копировать URL
          </button>
        </div>
        <p className="text-sm font-mono text-slate-200 break-all">
          {session?.page_url || "— (браузер ещё не открыл страницу)"}
        </p>
      </div>

      <div className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs uppercase tracking-wide text-slate-500">Лог действий браузера</p>
          <button
            type="button"
            className="btn-ghost text-xs"
            disabled={logs.length === 0}
            onClick={() => void copyLogs()}
          >
            <Copy size={12} />
            {copyOk ? "Скопировано" : "Копировать лог"}
          </button>
        </div>
        <DiagnosticLogPanel
          lines={logs}
          emptyLabel={
            live
              ? "Ожидание событий браузера…"
              : "Запустите браузер — здесь появятся шаги запуска, goto и ошибки."
          }
          maxHeightClass="max-h-56"
        />
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
            disabled={busy || !navReady}
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
          {live && vncUrl ? (
            <p className="px-3 py-2 text-xs text-slate-500 border-b border-slate-800">
              Если noVNC пишет «Failed to connect» — на VPS в{" "}
              <span className="font-mono">/etc/nginx/sites-available/insta</span> нужны заголовки
              WebSocket Upgrade (см.{" "}
              <span className="font-mono">deploy/host-nginx.conf.example</span>), затем{" "}
              <span className="font-mono">nginx -t && systemctl reload nginx</span>.
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

      {session?.error ? <p className="text-xs text-rose-300">{session.error}</p> : null}
    </div>
  );
}
