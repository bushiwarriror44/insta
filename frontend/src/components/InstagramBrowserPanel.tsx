import type { LucideIcon } from "lucide-react";
import {
  Bell,
  CheckCircle2,
  Clapperboard,
  Compass,
  Cookie,
  Copy,
  Eye,
  EyeOff,
  Film,
  Home,
  Keyboard,
  Link2,
  Loader2,
  LogIn,
  ExternalLink,
  ChevronDown,
  MessageCircle,
  MonitorPlay,
  Pencil,
  Power,
  RefreshCw,
  Send,
  Smartphone,
  Square,
  User,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, formatApiError, ApiError } from "../api/client";
import type {
  AccountTotpOut,
  BrowserSaveOut,
  BrowserSessionOut,
  DiagnosticLogLine,
  LoginSurface,
} from "../api/types";
import { useToast } from "../context/ToastContext";
import { CountryFlag } from "./CountryFlag";
import {
  DiagnosticLogPanel,
  copyTextToClipboard,
  formatDiagnosticLogPlain,
} from "./DiagnosticLogPanel";
import { StatusBadge } from "./StatusBadge";

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

const QUICK_NAV: { target: Exclude<BrowserNavTarget, "auto">; label: string; Icon: LucideIcon }[] = [
  { target: "home", label: "Лента", Icon: Home },
  { target: "reels", label: "Рилс", Icon: Film },
  { target: "explore", label: "Обзор", Icon: Compass },
  { target: "direct", label: "Директ", Icon: MessageCircle },
  { target: "activity", label: "Активность", Icon: Bell },
  { target: "profile", label: "Профиль", Icon: User },
  { target: "edit_profile", label: "Ред. профиль", Icon: Pencil },
  { target: "login", label: "Вход", Icon: LogIn },
];

export interface InstagramBrowserPanelProps {
  username: string;
  adminToken?: string | null;
  mode?: "standalone" | "setup";
  loginSurface?: LoginSurface;
  platform?: "instagram" | "youtube" | "tiktok";
  /** When false, browser start is blocked (account has no proxy). */
  hasProxy?: boolean;
  onSessionSaved?: (result: BrowserSaveOut) => void;
  onRunningChange?: (running: boolean) => void;
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
  if (out.length === prev.length) return prev;
  return out.slice(-300);
}

export function InstagramBrowserPanel({
  username,
  adminToken,
  mode = "standalone",
  loginSurface = "mobile",
  platform = "instagram",
  hasProxy = true,
  onSessionSaved,
  onRunningChange,
}: InstagramBrowserPanelProps) {
  const isStudio = platform === "youtube" || platform === "tiktok";
  const studioLabel = platform === "youtube" ? "YouTube Studio" : platform === "tiktok" ? "TikTok Studio" : "";
  const { push } = useToast();
  const [session, setSession] = useState<BrowserSessionOut | null>(null);
  const [logs, setLogs] = useState<DiagnosticLogLine[]>([]);
  const [savedOk, setSavedOk] = useState(false);
  const [busy, setBusy] = useState(false);
  const [code, setCode] = useState("");
  const [notesDraft, setNotesDraft] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [copyOk, setCopyOk] = useState(false);
  const [totpInfo, setTotpInfo] = useState<AccountTotpOut | null>(null);
  const [totpAvailable, setTotpAvailable] = useState(true);
  const [totpSeedCopied, setTotpSeedCopied] = useState(false);
  const [totpCodeCopied, setTotpCodeCopied] = useState(false);
  const [lastStatusAt, setLastStatusAt] = useState<Date | null>(null);
  const pollRef = useRef<number | null>(null);
  const totpPollRef = useRef<number | null>(null);
  const prevPageUrlForSaveRef = useRef<string | null | "__init__">("__init__");

  const applySession = useCallback((data: BrowserSessionOut) => {
    if (!data) return;
    setSession(data);
    setLogs((prev) => mergeLogs(prev, data.logs ?? []));
  }, []);

  const refreshStatus = useCallback(async () => {
    try {
      const data = await api.accounts.browserStatus(username);
      applySession(data);
      setLastStatusAt(new Date());
    } catch {
      /* ignore transient poll errors */
    }
  }, [username, applySession]);

  useEffect(() => {
    setSavedOk(false);
    setLogs([]);
    setLastStatusAt(null);
    prevPageUrlForSaveRef.current = "__init__";
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

  useEffect(() => {
    const u = session?.page_url ?? null;
    if (prevPageUrlForSaveRef.current === "__init__") {
      prevPageUrlForSaveRef.current = u;
      return;
    }
    if (prevPageUrlForSaveRef.current !== u) {
      setSavedOk(false);
      prevPageUrlForSaveRef.current = u;
    }
  }, [session?.page_url]);

  const live =
    !!session && ["running", "awaiting_code", "saved", "starting"].includes(session.status);

  useEffect(() => {
    const running =
      session?.status === "running" ||
      session?.status === "starting" ||
      session?.status === "awaiting_code";
    onRunningChange?.(Boolean(running));
  }, [session?.status, onRunningChange]);
  const navReady =
    !!session && ["running", "awaiting_code", "saved"].includes(session.status);

  useEffect(() => {
    setTotpInfo(null);
    setTotpAvailable(true);
  }, [username]);

  useEffect(() => {
    if (totpPollRef.current !== null) {
      window.clearInterval(totpPollRef.current);
      totpPollRef.current = null;
    }
    if (!live || !totpAvailable) return;

    let cancelled = false;

    async function tick() {
      try {
        const data = await api.accounts.getTotp(username);
        if (!cancelled) {
          setTotpInfo(data);
          setTotpAvailable(true);
        }
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setTotpAvailable(false);
          setTotpInfo(null);
        }
      }
    }

    void tick();
    totpPollRef.current = window.setInterval(() => void tick(), 1000);
    return () => {
      cancelled = true;
      if (totpPollRef.current !== null) {
        window.clearInterval(totpPollRef.current);
        totpPollRef.current = null;
      }
    };
  }, [live, totpAvailable, username]);

  const vncPath = session?.vnc_path?.replace(/^\//, "") ?? "";

  const vncUrl = useMemo(() => {
    if (!vncPath || !session || ["stopped", "error"].includes(session.status)) return null;
    const params = new URLSearchParams({
      autoconnect: "true",
      resize: "scale",
      path: vncPath,
      quality: "3",
      compression: "8",
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

  const isSetup = mode === "setup";
  const showBlankWarning =
    session?.status === "running" &&
    Boolean(
      session.warning ||
        session.page_url === "about:blank" ||
        session.page_url?.startsWith("chrome://") ||
        session.page_url?.startsWith("chrome-error://")
    );

  const setupAutoOpenLine = isStudio
    ? platform === "youtube"
      ? "YouTube Studio (и при необходимости Google) откроется автоматически через прокси аккаунта"
      : "TikTok Studio откроется автоматически через прокси аккаунта"
    : "Instagram откроется автоматически через прокси аккаунта";

  const loginFieldLabel =
    platform === "youtube"
      ? "Логин (email Google)"
      : platform === "tiktok"
        ? "Логин (email / телефон TikTok)"
        : "Логин (email / телефон / username)";

  const vncIframeTitle =
    platform === "youtube"
      ? `Браузер VNC YouTube · @${username}`
      : platform === "tiktok"
        ? `Браузер VNC TikTok · @${username}`
        : `Браузер VNC Instagram · @${username}`;

  const vncPlaceholder =
    platform === "youtube"
      ? "Запустите браузер, чтобы увидеть YouTube / Google в noVNC"
      : platform === "tiktok"
        ? "Запустите браузер, чтобы увидеть TikTok Studio в noVNC"
        : "Запустите браузер, чтобы увидеть Instagram через noVNC";

  const blankWarningInner = useMemo(() => {
    if (!session || session.status !== "running") return null;
    const warnText = session.warning?.trim();
    if (warnText) {
      return <>{warnText}</>;
    }
    if (isStudio) {
      if (platform === "youtube") {
        return (
          <>
            {studioLabel} не загрузился или завис — нажмите «Открыть Studio» / «Google автозаполнение» или
            введите URL вручную в VNC. Google через mobile-прокси часто грузится 1–2 минуты.
          </>
        );
      }
      return (
        <>
          {studioLabel} не загрузился или завис — нажмите «Открыть Studio» или введите URL вручную в VNC.
          TikTok через mobile-прокси иногда грузится дольше обычного.
        </>
      );
    }
    if (session.proxy_instagram_login_http_status === 429) {
      return (
        <>
          Временное ограничение запросов с IP прокси{" "}
          <span className="font-mono">{session.proxy_ip ?? ""}</span> (HTTP 429). Подождите 30–60 минут
          или смените прокси, затем нажмите «Открыть Instagram».
        </>
      );
    }
    return (
      <>
        Страница пустая — нажмите «Открыть Instagram» или «Вход», либо введите адрес в VNC.
      </>
    );
  }, [session, isStudio, studioLabel, platform]);
  async function startBrowser(withStudioAutofill = false) {
    if (!hasProxy) {
      push("Сначала назначьте прокси", "error");
      return;
    }
    setBusy(true);
    try {
      const data = await api.accounts.browserStart(username, {
        loginSurface,
        autofill: isStudio && withStudioAutofill,
      });
      applySession(data);
      setSavedOk(false);
      push("Браузер запущен", "success");
    } catch (err) {
      push(formatApiError(err), "error");
    } finally {
      setBusy(false);
    }
  }

  async function openStudio(opts?: { autofill?: boolean }) {
    setBusy(true);
    try {
      const data = await api.accounts.browserOpenInstagram(username, {
        autofill: opts?.autofill,
        target: "auto",
      });
      applySession(data);
      push(
        opts?.autofill
          ? platform === "youtube"
            ? `Google: автозаполнение (${studioLabel})`
            : `Автозаполнение логина (${studioLabel})`
          : `Открытие ${studioLabel}`,
        "success"
      );
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
        reels: "Переход в Рилс",
        explore: "Переход в Обзор",
        direct: "Переход в Директ",
        activity: "Переход в Активность",
        profile: "Переход в профиль",
        edit_profile: "Переход в редактирование профиля",
        login: opts?.autofill ? "Вход + автозаполнение" : "Переход на вход",
        auto: "Открытие Instagram",
      };
      push(labels[opts?.target ?? "auto"] ?? "Запрос на открытие Instagram отправлен", "success");
    } catch (err) {
      push(formatApiError(err), "error");
    } finally {
      setBusy(false);
    }
  }

  async function saveSession(opts?: { stopAfterSave?: boolean }) {
    const stopAfterSave = Boolean(opts?.stopAfterSave);
    setBusy(true);
    try {
      const urlBeforeSave = session?.page_url ?? null;
      const data = await api.accounts.browserSave(username, { stopAfterSave });
      const merged: BrowserSaveOut = {
        ...data,
        page_url: data.page_url ?? urlBeforeSave,
      };
      applySession(merged);
      if (data.overall_ok) {
        prevPageUrlForSaveRef.current = merged.page_url ?? null;
        setSavedOk(true);
        onSessionSaved?.(data);
        push(
          stopAfterSave
            ? "Сессия и куки сохранены, браузер остановлен"
            : "Сессия и куки сохранены (в БД)",
          "success"
        );
      } else {
        setSavedOk(false);
        const err =
          data.logs?.find((l) => l.level === "error")?.message ??
          "Не удалось сохранить sessionid и куки из браузера";
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

  async function copyTotpCode() {
    if (!totpInfo?.code) return;
    setCode(totpInfo.code);
    const ok = await copyTextToClipboard(totpInfo.code);
    push(ok ? "Код TOTP скопирован" : "Не удалось скопировать код TOTP", ok ? "success" : "error");
    if (ok) {
      setTotpCodeCopied(true);
      window.setTimeout(() => setTotpCodeCopied(false), 2000);
    }
  }

  async function copyTotpSeed() {
    if (!totpInfo?.totp_seed) return;
    const ok = await copyTextToClipboard(totpInfo.totp_seed);
    push(
      ok ? "Секретный ключ TOTP скопирован" : "Не удалось скопировать ключ TOTP",
      ok ? "success" : "error"
    );
    if (ok) {
      setTotpSeedCopied(true);
      window.setTimeout(() => setTotpSeedCopied(false), 2000);
    }
  }

  const setupStep = savedOk ? 4 : live ? 2 : 1;

  const showStatusSkeleton =
    session?.status === "starting" || (busy && !!session);

  const showVncSkeleton =
    Boolean(vncUrl) && (session?.status === "starting" || (busy && !!session));

  const browserStatusSubline = useMemo(() => {
    if (!session) return null;
    if (session.status === "error" && session.error?.trim()) {
      return session.error.trim();
    }
    if (session.status === "awaiting_code") {
      return "Введите код 2FA в поле слева или в окне браузера";
    }
    if (session.status === "starting") {
      return "Инициализация прокси и браузера…";
    }
    if (session.status === "running") {
      if (showBlankWarning) return "Страница ещё не готова — см. предупреждение выше";
      if (savedOk) return "Сессия сохранена, при необходимости остановите браузер";
      return navReady ? "Можно переходить по разделам и сохранять сессию" : "Скоро откроется навигация";
    }
    if (session.status === "saved") {
      return "Сессия записана — при необходимости остановите браузер";
    }
    if (!live && session.status === "stopped") {
      return "Запустите браузер для работы в VNC";
    }
    return null;
  }, [session, showBlankWarning, savedOk, navReady, live]);

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
            Запустите браузер — {setupAutoOpenLine}
          </li>
          <li className={setupStep >= 2 ? "text-slate-200" : ""}>
            При 2FA/challenge введите код в браузере или в поле слева
          </li>
          <li className={setupStep >= 3 || (live && !savedOk) ? "text-slate-200" : ""}>
            <strong>Сохраните сессию и куки</strong> — обязательный шаг перед завершением настройки
          </li>
          <li className={setupStep >= 4 ? "text-emerald-300" : ""}>
            Остановите браузер — web-cookie останется в БД; для автопостинга сделайте mint
          </li>
        </ol>
      ) : null}

      <div
        className="rounded-xl border border-rose-500/30 bg-rose-950/20 p-3 text-xs text-rose-100 max-w-prose transition-colors duration-200"
        role="status"
      >
        VNC даёт полный доступ к экрану сервера, включая пароль в браузере. Используйте только
        на доверенной сети и с ADMIN_TOKEN.
      </div>

      {savedOk ? (
        <div className="rounded-lg border border-emerald-700/50 bg-emerald-950/30 p-3 text-sm text-emerald-200 space-y-1 max-w-prose transition-shadow duration-200">
          <div className="flex items-center gap-2">
            <CheckCircle2 size={16} />
            Web-сессия сохранена (sessionid в БД)
          </div>
          <p className="text-xs text-emerald-100/90 max-w-prose">
            Это web-cookie. Для стабильного автопостинга один раз нажмите «Подготовить к
            автопостингу» или поставьте пост в очередь — вход пойдёт по паролю и создаст mobile
            dump.
          </p>
        </div>
      ) : null}

      {showBlankWarning ? (
        <div
          className="rounded-lg border border-amber-500/40 bg-amber-950/30 p-3 text-sm text-amber-100 max-w-prose transition-colors duration-200"
          role="alert"
          aria-live="polite"
        >
          {blankWarningInner}
        </div>
      ) : null}

      {platform === "youtube" && live ? (
        <div className="rounded-lg border border-slate-600 bg-slate-900/40 p-3 text-xs text-slate-400 space-y-1 max-w-prose transition-colors duration-200">
          <p className="text-slate-300 font-medium">YouTube / Google</p>
          <p className="max-w-prose">
            Успешная предпроверка прокси (HEAD) не гарантирует живую сессию: если Studio снова ведёт на
            вход Google — залогиньтесь в VNC и нажмите «Сохранить сессию и куки». Для контроля
            используйте liveness / test-connection в админке.
          </p>
        </div>
      ) : null}

      {session?.account_username ? (
        <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-3 text-sm text-slate-300 space-y-2">
          <p className="text-xs uppercase tracking-wide text-slate-500">Аккаунт</p>
          <p>
            <span className="text-slate-400">Имя:</span>{" "}
            <span className="text-slate-100 font-mono">@{session.account_username}</span>
          </p>
          <p>
            <span className="text-slate-400">{loginFieldLabel}:</span>{" "}
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
            {platform === "instagram" && session.proxy_instagram_reachable != null ? (
              <span
                className={
                  session.proxy_instagram_reachable ? "text-emerald-300" : "text-rose-300"
                }
              >
                Instagram API: {session.proxy_instagram_reachable ? "доступен" : "недоступен"}
              </span>
            ) : null}
            {platform === "instagram" && session.proxy_instagram_login_reachable != null ? (
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
            {platform !== "instagram" ? (
              <span className="text-slate-500 text-xs">
                Проверки Instagram API / страницы входа относятся только к аккаунтам Instagram.
              </span>
            ) : null}
          </p>
        </div>
      ) : null}

      <div className="space-y-3" aria-label="Управление браузером">
        <div
          className="flex flex-col gap-2 rounded-lg border border-slate-800 bg-slate-900/40 p-3 transition-colors duration-200 sm:flex-row sm:flex-wrap sm:items-start sm:justify-between"
          aria-live="polite"
        >
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[10px] uppercase tracking-wide text-slate-500">Сейчас</span>
              {session ? (
                <StatusBadge value={session.status} />
              ) : showStatusSkeleton ? (
                <span
                  className="inline-block h-5 w-24 animate-pulse rounded-full bg-slate-700/60"
                  aria-hidden
                />
              ) : (
                <span className="text-xs text-slate-500">загрузка…</span>
              )}
              {session?.awaiting_code ? (
                <span className="text-[11px] text-amber-300">нужен код 2FA</span>
              ) : null}
              {lastStatusAt ? (
                <span className="text-[11px] text-slate-500">
                  обновлено{" "}
                  {lastStatusAt.toLocaleTimeString(undefined, {
                    hour: "2-digit",
                    minute: "2-digit",
                    second: "2-digit",
                  })}
                </span>
              ) : null}
            </div>
            {browserStatusSubline ? (
              <p className="max-w-prose text-xs text-slate-400">{browserStatusSubline}</p>
            ) : null}
          </div>
          <button
            type="button"
            className="btn-ghost text-xs shrink-0 self-start sm:self-center"
            disabled={busy}
            title="Запросить статус с API сейчас"
            onClick={() => void refreshStatus()}
          >
            <RefreshCw size={14} className="shrink-0" />
            Обновить статус
          </button>
        </div>

        <div>
          <p className="mb-2 text-[10px] uppercase tracking-wide text-slate-500">Запуск и открытие</p>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="btn-primary"
              disabled={busy || live || !hasProxy}
              title={hasProxy ? undefined : "Сначала назначьте прокси"}
              onClick={() => void startBrowser(false)}
            >
              <MonitorPlay size={16} className={busy && !live ? "animate-spin" : ""} />
              Запустить браузер
            </button>
            {isStudio ? (
              <>
                <button
                  type="button"
                  className="btn-ghost hidden sm:inline-flex"
                  disabled={busy || !navReady}
                  onClick={() => void openStudio()}
                >
                  <Clapperboard size={16} />
                  Открыть Studio
                </button>
                {platform === "youtube" ? (
                  <button
                    type="button"
                    className="btn-ghost text-xs hidden sm:inline-flex"
                    disabled={busy || !navReady}
                    onClick={() => void openStudio({ autofill: true })}
                  >
                    <Keyboard size={14} className="shrink-0" />
                    Google автозаполнение
                  </button>
                ) : (
                  <button
                    type="button"
                    className="btn-ghost text-xs hidden sm:inline-flex"
                    disabled={busy || !navReady}
                    onClick={() => void openStudio({ autofill: true })}
                  >
                    <Keyboard size={14} className="shrink-0" />
                    Автозаполнение логина
                  </button>
                )}
                <details className="group relative w-full sm:hidden">
                  <summary className="btn-ghost list-none inline-flex w-full cursor-pointer items-center justify-center gap-1 text-xs [&::-webkit-details-marker]:hidden">
                    <ChevronDown
                      size={14}
                      className="shrink-0 transition-transform group-open:rotate-180"
                      aria-hidden
                    />
                    Ещё: Studio
                  </summary>
                  <div className="mt-2 flex flex-col gap-2 border-t border-slate-800 pt-2">
                    <button
                      type="button"
                      className="btn-ghost w-full justify-center"
                      disabled={busy || !navReady}
                      onClick={() => void openStudio()}
                    >
                      <Clapperboard size={16} />
                      Открыть Studio
                    </button>
                    {platform === "youtube" ? (
                      <button
                        type="button"
                        className="btn-ghost w-full justify-center text-xs"
                        disabled={busy || !navReady}
                        onClick={() => void openStudio({ autofill: true })}
                      >
                        <Keyboard size={14} className="shrink-0" />
                        Google автозаполнение
                      </button>
                    ) : (
                      <button
                        type="button"
                        className="btn-ghost w-full justify-center text-xs"
                        disabled={busy || !navReady}
                        onClick={() => void openStudio({ autofill: true })}
                      >
                        <Keyboard size={14} className="shrink-0" />
                        Автозаполнение логина
                      </button>
                    )}
                  </div>
                </details>
              </>
            ) : (
              <>
                <button
                  type="button"
                  className="btn-ghost hidden sm:inline-flex"
                  disabled={busy || !navReady}
                  onClick={() => void openInstagram({ target: "auto" })}
                >
                  <Smartphone size={16} />
                  Открыть Instagram
                </button>
                <button
                  type="button"
                  className="btn-ghost text-xs hidden sm:inline-flex"
                  disabled={busy || !navReady}
                  onClick={() => void openInstagram({ target: "login", autofill: true })}
                >
                  <LogIn size={14} className="shrink-0" />
                  Заполнить логин
                </button>
                <details className="group relative w-full sm:hidden">
                  <summary className="btn-ghost list-none inline-flex w-full cursor-pointer items-center justify-center gap-1 text-xs [&::-webkit-details-marker]:hidden">
                    <ChevronDown
                      size={14}
                      className="shrink-0 transition-transform group-open:rotate-180"
                      aria-hidden
                    />
                    Ещё: Instagram
                  </summary>
                  <div className="mt-2 flex flex-col gap-2 border-t border-slate-800 pt-2">
                    <button
                      type="button"
                      className="btn-ghost w-full justify-center"
                      disabled={busy || !navReady}
                      onClick={() => void openInstagram({ target: "auto" })}
                    >
                      <Smartphone size={16} />
                      Открыть Instagram
                    </button>
                    <button
                      type="button"
                      className="btn-ghost w-full justify-center text-xs"
                      disabled={busy || !navReady}
                      onClick={() => void openInstagram({ target: "login", autofill: true })}
                    >
                      <LogIn size={14} className="shrink-0" />
                      Заполнить логин
                    </button>
                  </div>
                </details>
              </>
            )}
          </div>
        </div>

        <div>
          <p className="mb-2 text-[10px] uppercase tracking-wide text-slate-500">Сессия и VNC</p>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="btn-ghost"
              disabled={busy || !navReady || savedOk}
              onClick={() => void saveSession({ stopAfterSave: false })}
            >
              <Cookie size={16} />
              Сохранить сессию и куки
            </button>
            <button type="button" className="btn-ghost" disabled={busy || !live} onClick={stopBrowser}>
              <Square size={16} />
              Остановить
            </button>
            <button
              type="button"
              className="btn-ghost text-xs hidden sm:inline-flex"
              disabled={busy || !navReady}
              title="Сохранить web-cookie в БД и закрыть VNC"
              onClick={() => void saveSession({ stopAfterSave: true })}
            >
              <Power size={14} className="shrink-0" />
              Сохранить и остановить
            </button>
            {live && vncUrl ? (
              <button
                type="button"
                className="btn-ghost text-xs hidden sm:inline-flex"
                onClick={() => {
                  window.open(vncUrl, "_blank", "noopener,noreferrer");
                }}
              >
                <ExternalLink size={14} className="shrink-0" />
                VNC в новой вкладке
              </button>
            ) : null}
            <details className="group relative w-full sm:hidden">
              <summary className="btn-ghost list-none inline-flex w-full cursor-pointer items-center justify-center gap-1 text-xs [&::-webkit-details-marker]:hidden">
                <ChevronDown
                  size={14}
                  className="shrink-0 transition-transform group-open:rotate-180"
                  aria-hidden
                />
                Ещё: сессия
              </summary>
              <div className="mt-2 flex flex-col gap-2 border-t border-slate-800 pt-2">
                <button
                  type="button"
                  className="btn-ghost w-full justify-center text-xs"
                  disabled={busy || !navReady}
                  title="Сохранить web-cookie в БД и закрыть VNC"
                  onClick={() => void saveSession({ stopAfterSave: true })}
                >
                  <Power size={14} className="shrink-0" />
                  Сохранить и остановить
                </button>
                {live && vncUrl ? (
                  <button
                    type="button"
                    className="btn-ghost w-full justify-center text-xs"
                    onClick={() => {
                      window.open(vncUrl, "_blank", "noopener,noreferrer");
                    }}
                  >
                    <ExternalLink size={14} className="shrink-0" />
                    VNC в новой вкладке
                  </button>
                ) : null}
              </div>
            </details>
          </div>
        </div>
      </div>
      {!hasProxy ? (
        <p className="text-xs text-amber-300">Сначала назначьте прокси</p>
      ) : null}

      {!isStudio ? (
      <div className="rounded-lg border border-slate-700 bg-slate-900/40 p-3 space-y-2">
        <p className="text-xs uppercase tracking-wide text-slate-500">Быстрый переход в Instagram</p>
        <div className="-mx-1 flex gap-2 overflow-x-auto pb-1 px-1 sm:flex-wrap sm:overflow-visible">
          {QUICK_NAV.map((item) => {
            const NavIcon = item.Icon;
            return (
              <button
                key={item.target}
                type="button"
                className="btn-ghost text-xs inline-flex shrink-0 items-center gap-1 sm:shrink"
                disabled={busy || !navReady}
                onClick={() => void openInstagram({ target: item.target })}
              >
                <NavIcon size={14} className="shrink-0 opacity-90" />
                {item.label}
              </button>
            );
          })}
        </div>
        <p className="text-xs text-slate-500">
          Страница откроется внутри noVNC-браузера через прокси аккаунта.
        </p>
      </div>
      ) : null}

      <div className="rounded-lg border border-slate-700 bg-slate-900/40 p-3 space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs uppercase tracking-wide text-slate-500">Текущая страница</p>
          <button
            type="button"
            className="btn-ghost text-xs inline-flex items-center gap-1"
            disabled={!session?.page_url}
            onClick={() => void copyPageUrl()}
          >
            <Link2 size={12} className="shrink-0" />
            Копировать URL
          </button>
        </div>
        <p className="text-sm font-mono text-slate-200 break-all">
          {session?.page_url || "— (браузер ещё не открыл страницу)"}
        </p>
      </div>

      <section
        className="rounded-lg border border-slate-700 bg-slate-900/40 p-3 space-y-2 transition-colors duration-200"
        role="region"
        aria-labelledby={`browser-diagnostics-heading-${username}`}
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3
            id={`browser-diagnostics-heading-${username}`}
            className="text-[10px] uppercase tracking-wide text-slate-500"
          >
            Диагностика
          </h3>
          <button
            type="button"
            className="btn-ghost text-xs inline-flex items-center gap-1"
            disabled={logs.length === 0}
            onClick={() => void copyLogs()}
          >
            <Copy size={12} className="shrink-0" />
            {copyOk ? "Скопировано" : "Копировать лог"}
          </button>
        </div>
        <DiagnosticLogPanel
          lines={logs}
          showHeaderCopy={false}
          headerTitle="События"
          emptyLabel={
            live
              ? "Ожидание событий браузера…"
              : "Запустите браузер — здесь появятся шаги запуска, goto и ошибки."
          }
          maxHeightClass="max-h-56"
        />
      </section>

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
          {totpInfo ? (
            <div className="rounded-lg border border-emerald-800/50 bg-emerald-950/20 p-2 space-y-2">
              <p className="text-[10px] uppercase tracking-wide text-emerald-400">TOTP сейчас</p>
              <p className="font-mono text-lg tracking-widest text-emerald-100">
                {totpInfo.code}
                <span className="ml-2 text-xs text-slate-400 tabular-nums">
                  {totpInfo.seconds_remaining}s
                </span>
              </p>
              <button
                type="button"
                className="btn-ghost text-xs w-full"
                onClick={() => void copyTotpCode()}
              >
                <Copy size={12} />
                {totpCodeCopied ? "Скопировано" : "Копировать код"}
              </button>
              <button
                type="button"
                className="btn-ghost text-xs w-full"
                onClick={() => void copyTotpSeed()}
              >
                <Copy size={12} />
                {totpSeedCopied ? "Скопировано" : "Копировать секретный ключ TOTP"}
              </button>
            </div>
          ) : session?.awaiting_code && !totpAvailable ? (
            <p className="text-xs text-amber-300">
              Секрет TOTP не задан — добавьте в настройках аккаунта
            </p>
          ) : null}
          <p className="text-xs text-slate-500">
            Введите код здесь или прямо в окне браузера справа.
          </p>
        </div>

        <div className="relative rounded-lg border border-slate-700 bg-black/40 overflow-hidden min-h-[360px] transition-colors duration-200">
          {live && vncUrl ? (
            <p className="px-3 py-2 text-xs text-slate-500 border-b border-slate-800 max-w-prose">
              Если noVNC не подключается — на VPS в{" "}
              <span className="font-mono">/etc/nginx/sites-available/insta</span> нужны заголовки
              WebSocket Upgrade (см.{" "}
              <span className="font-mono">deploy/host-nginx.conf.example</span>), затем{" "}
              <span className="font-mono">nginx -t && systemctl reload nginx</span>.
            </p>
          ) : null}
          {vncUrl ? (
            <>
              <iframe
                title={vncIframeTitle}
                src={vncUrl}
                className="relative z-0 w-full h-[600px] bg-black"
                allow="clipboard-read; clipboard-write"
              />
              {showVncSkeleton ? (
                <div
                  className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 bg-black/55 backdrop-blur-[1px] transition-opacity duration-200"
                  aria-busy="true"
                  aria-label="Подключение к VNC"
                >
                  <Loader2 className="h-8 w-8 animate-spin text-slate-400" aria-hidden />
                  <span className="text-xs text-slate-400">Подключение к VNC…</span>
                  <div className="h-2 w-40 max-w-[80%] animate-pulse rounded bg-slate-700/80" aria-hidden />
                </div>
              ) : null}
            </>
          ) : session?.status === "starting" ? (
            <div
              className="flex h-[360px] flex-col items-center justify-center gap-3 px-4"
              aria-busy="true"
              aria-label="Ожидание VNC"
            >
              <Loader2 className="h-8 w-8 animate-spin text-slate-500" aria-hidden />
              <div className="h-2 w-48 max-w-full animate-pulse rounded bg-slate-800" aria-hidden />
              <p className="text-center text-sm text-slate-500">{vncPlaceholder}</p>
            </div>
          ) : (
            <div className="flex h-[360px] items-center justify-center text-sm text-slate-500 px-4 text-center max-w-prose mx-auto">
              {vncPlaceholder}
            </div>
          )}
        </div>
      </div>

      {session?.error ? <p className="text-xs text-rose-300">{session.error}</p> : null}
    </div>
  );
}
