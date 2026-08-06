import {
  ArrowLeft,
  CheckCircle2,
  KeyRound,
  Monitor,
  MonitorPlay,
  RefreshCw,
  Smartphone,
  Sparkles,
  XCircle,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { api, formatApiError } from "../api/client";
import type {
  AccountConnectionTestOut,
  AccountOut,
  AccountSessionUpdate,
  BrowserSaveOut,
  FirstLoginOut,
  InstagramAuthStepOut,
  LoginSurface,
} from "../api/types";
import { DiagnosticLogPanel } from "./DiagnosticLogPanel";
import { InstagramBrowserPanel } from "./InstagramBrowserPanel";
import { Modal } from "./Modal";
import { useToast } from "../context/ToastContext";
import { useAuth } from "../context/AuthContext";

type ConnectionMode = "choose" | "auto" | "browser" | "manual";

interface Props {
  account: AccountOut | null;
  open: boolean;
  onClose: () => void;
  onCompleted: () => void | Promise<void>;
}

export function isSessionMissing(auth: Pick<InstagramAuthStepOut, "error" | "error_code">): boolean {
  if (auth.error_code === "session_missing") return true;
  // Expired / challenge means a session was present — do not treat as "missing".
  if (auth.error_code === "session_expired" || auth.error_code === "challenge_required") {
    return false;
  }
  if (!auth.error) return false;
  const lower = auth.error.toLowerCase();
  return (
    lower.includes("нет session_id") ||
    lower.includes("импортируйте sessionid") ||
    lower.includes("сессия не найдена") ||
    auth.error.includes("файла сессии") ||
    auth.error.includes("нет файла сессии")
  );
}

/** Mobile probe rejected sessionid (common for Dolphin / browser web cookies). */
export function isSessionExpired(auth: Pick<InstagramAuthStepOut, "error" | "error_code">): boolean {
  if (auth.error_code === "session_expired") return true;
  if (!auth.error) return false;
  const lower = auth.error.toLowerCase();
  return lower.includes("недействителен") || lower.includes("истёк") || lower.includes("истек");
}

export const SESSION_EXPIRED_MOBILE_HINT =
  "Mobile API отклонил web-cookie из Dolphin. Автопостинг возможен через пароль аккаунта (очередь сама войдёт без мёртвого sessionid) или — рекомендуется — один раз нажмите «Подготовить к автопостингу», чтобы создать стабильную mobile-сессию (нужны пароль и при 2FA — TOTP). Cookies-only проверка и экспорт в Dolphin не требуют mobile API.";

export function SessionSetupModal({ account, open, onClose, onCompleted }: Props) {
  const { push } = useToast();
  const { state: authState } = useAuth();
  const adminToken = authState.state === "authed" ? authState.token : null;
  const [connectionMode, setConnectionMode] = useState<ConnectionMode>("choose");
  const [loginSurface, setLoginSurface] = useState<LoginSurface>("mobile");
  const [autoBusy, setAutoBusy] = useState(false);
  const [manualBusy, setManualBusy] = useState(false);
  const [sessionId, setSessionId] = useState("");
  const [firstLoginResult, setFirstLoginResult] = useState<FirstLoginOut | null>(null);
  const [connectionResult, setConnectionResult] = useState<AccountConnectionTestOut | null>(null);
  const [browserSuccess, setBrowserSuccess] = useState(false);
  const [manualSaved, setManualSaved] = useState(false);
  const [loginDebugUrl, setLoginDebugUrl] = useState<string | null>(null);
  const loginDebugUrlRef = useRef<string | null>(null);

  const success =
    firstLoginResult?.ok === true ||
    connectionResult?.overall_ok === true ||
    firstLoginResult?.connection_test?.overall_ok === true ||
    browserSuccess ||
    manualSaved;

  useEffect(() => {
    if (!open) return;
    setConnectionMode("choose");
    setLoginSurface(account?.login_surface === "desktop" ? "desktop" : "mobile");
    setSessionId("");
    setFirstLoginResult(null);
    setConnectionResult(null);
    setBrowserSuccess(false);
    setManualSaved(false);
    setAutoBusy(false);
    setManualBusy(false);
    if (loginDebugUrlRef.current) {
      URL.revokeObjectURL(loginDebugUrlRef.current);
      loginDebugUrlRef.current = null;
    }
    setLoginDebugUrl(null);
  }, [open, account?.username]);

  useEffect(() => {
    return () => {
      if (loginDebugUrlRef.current) {
        URL.revokeObjectURL(loginDebugUrlRef.current);
        loginDebugUrlRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (!open || !account || !firstLoginResult?.login_debug_available) {
      if (loginDebugUrlRef.current) {
        URL.revokeObjectURL(loginDebugUrlRef.current);
        loginDebugUrlRef.current = null;
      }
      setLoginDebugUrl(null);
      return;
    }

    let cancelled = false;
    (async () => {
      try {
        const url = await api.accounts.fetchLoginDebugScreenshot(account.username);
        if (cancelled) {
          URL.revokeObjectURL(url);
          return;
        }
        if (loginDebugUrlRef.current) {
          URL.revokeObjectURL(loginDebugUrlRef.current);
        }
        loginDebugUrlRef.current = url;
        setLoginDebugUrl(url);
      } catch {
        if (!cancelled) {
          setLoginDebugUrl(null);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [open, account?.username, firstLoginResult?.login_debug_available]);

  useEffect(() => {
    if (firstLoginResult?.challenge || firstLoginResult?.browser_tab_hint) {
      setConnectionMode("browser");
    }
  }, [firstLoginResult?.challenge, firstLoginResult?.browser_tab_hint]);

  function handleBrowserSessionSaved(result: BrowserSaveOut) {
    if (result.connection_test) {
      setConnectionResult(result.connection_test);
    }
    setBrowserSuccess(result.overall_ok === true);
  }

  async function runAutoLogin() {
    if (!account) return;
    setAutoBusy(true);
    setFirstLoginResult(null);
    setConnectionResult(null);
    setBrowserSuccess(false);
    try {
      const data = await api.accounts.firstLogin(account.username, { loginSurface });
      setFirstLoginResult(data);
      if (data.connection_test) {
        setConnectionResult(data.connection_test);
      }
      if (data.ok) {
        push(`@${account.username}: сессия создана`, "success");
      } else if (data.challenge) {
        push("Требуется подтверждение — переключитесь на вход через браузер", "error");
        setConnectionMode("browser");
      } else {
        push(data.error ?? "Автовход не удался", "error");
      }
    } catch (err) {
      push(formatApiError(err), "error");
    } finally {
      setAutoBusy(false);
    }
  }

  async function submitManual(e: React.FormEvent) {
    e.preventDefault();
    if (!account) return;
    const trimmed = decodeURIComponent(sessionId.trim().replace(/\+/g, " "));
    if (trimmed.length < 31) {
      push("Вставьте корректную cookie sessionid (31+ символов)", "error");
      return;
    }
    setManualBusy(true);
    setConnectionResult(null);
    setBrowserSuccess(false);
    try {
      const payload: AccountSessionUpdate = { session_id: trimmed };
      await api.accounts.updateSession(account.username, payload);
      setSessionId(trimmed);
      setManualSaved(true);
      // Do not auto-call testConnection — mobile probe often burns the web sessionid.
      push(`@${account.username}: сессия сохранена`, "success");
    } catch (err) {
      push(formatApiError(err), "error");
    } finally {
      setManualBusy(false);
    }
  }

  async function handleDone() {
    await onCompleted();
    onClose();
  }

  const logs =
    connectionResult?.logs ??
    firstLoginResult?.logs ??
    firstLoginResult?.connection_test?.logs ??
    [];

  const showBack = connectionMode !== "choose" && !success;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Настройка сессии · @${account?.username ?? ""}`}
      widthClass="max-w-4xl"
      footer={
        <>
          {showBack ? (
            <button
              type="button"
              onClick={() => setConnectionMode("choose")}
              className="btn-ghost"
            >
              <ArrowLeft size={16} /> Назад
            </button>
          ) : (
            <button type="button" onClick={onClose} className="btn-ghost">
              <XCircle size={16} /> Закрыть
            </button>
          )}
          {success ? (
            <button type="button" className="btn-primary" onClick={handleDone}>
              <CheckCircle2 size={16} /> Готово
            </button>
          ) : connectionMode === "choose" ? null : connectionMode === "auto" ? (
            <button
              type="button"
              className="btn-primary"
              disabled={autoBusy || !account}
              onClick={runAutoLogin}
            >
              <Sparkles size={16} className={autoBusy ? "animate-spin" : ""} />
              {autoBusy ? "Создание сессии…" : "Создать сессию"}
            </button>
          ) : connectionMode === "browser" ? (
            <button
              type="button"
              className="btn-primary"
              disabled={!browserSuccess}
              onClick={handleDone}
              title={browserSuccess ? undefined : "Сначала сохраните сессию в браузере"}
            >
              <CheckCircle2 size={16} /> Готово
            </button>
          ) : (
            <button
              form="session-setup-manual-form"
              type="submit"
              className="btn-primary"
              disabled={manualBusy}
            >
              <KeyRound size={16} />
              {manualBusy ? "Сохранение…" : "Сохранить сессию"}
            </button>
          )}
        </>
      }
    >
      <div className="space-y-4">
        <div className="rounded-xl border border-amber-500/40 bg-amber-950/30 p-3 text-sm text-amber-100">
          Для автопостинга нужна Instagram-сессия. Прокси аккаунта (
          <span className="font-mono text-xs">{account?.proxy_label ?? "—"}</span>) должен совпадать с
          тем, через который вы входите в Instagram.
        </div>

        {connectionMode === "choose" ? (
          <div className="space-y-4">
            <div className="space-y-2">
              <p className="text-sm text-slate-300">Режим браузера:</p>
              <div className="grid gap-3 sm:grid-cols-2">
                <button
                  type="button"
                  className={`rounded-xl border p-4 text-left transition-colors ${
                    loginSurface === "mobile"
                      ? "border-brand-500/60 bg-brand-950/30"
                      : "border-slate-700 bg-slate-900/50 hover:border-brand-500/50"
                  }`}
                  onClick={() => setLoginSurface("mobile")}
                >
                  <div className="flex items-center gap-2 text-white font-medium mb-2">
                    <Smartphone size={18} className="text-brand-400" />
                    Мобильный
                  </div>
                  <p className="text-xs text-slate-400">
                    Instagram как с телефона, совпадает с fingerprint аккаунта (рекомендуется).
                  </p>
                </button>
                <button
                  type="button"
                  className={`rounded-xl border p-4 text-left transition-colors ${
                    loginSurface === "desktop"
                      ? "border-sky-500/60 bg-sky-950/30"
                      : "border-slate-700 bg-slate-900/50 hover:border-sky-500/50"
                  }`}
                  onClick={() => setLoginSurface("desktop")}
                >
                  <div className="flex items-center gap-2 text-white font-medium mb-2">
                    <Monitor size={18} className="text-sky-400" />
                    Десктоп
                  </div>
                  <p className="text-xs text-slate-400">
                    Классический веб-логин, проще при проблемах с формой входа.
                  </p>
                </button>
              </div>
              {account?.has_session_id &&
              account.login_surface &&
              account.login_surface !== loginSurface ? (
                <div className="rounded-lg border border-amber-500/40 bg-amber-950/30 p-3 text-xs text-amber-100">
                  Смена режима после сохранения сессии может потребовать повторного входа.
                </div>
              ) : null}
            </div>
            <p className="text-sm text-slate-300">Выберите способ подключения:</p>
            <div className="grid gap-3 sm:grid-cols-2">
              <button
                type="button"
                className="rounded-xl border border-slate-700 bg-slate-900/50 p-4 text-left hover:border-brand-500/50 hover:bg-slate-900 transition-colors"
                onClick={() => setConnectionMode("auto")}
              >
                <div className="flex items-center gap-2 text-white font-medium mb-2">
                  <Sparkles size={18} className="text-brand-400" />
                  Автоматически
                </div>
                <p className="text-xs text-slate-400">
                  Сервер выполнит вход через Playwright. Подходит, если 2FA настроена через TOTP seed.
                </p>
              </button>
              <button
                type="button"
                className="rounded-xl border border-slate-700 bg-slate-900/50 p-4 text-left hover:border-sky-500/50 hover:bg-slate-900 transition-colors"
                onClick={() => setConnectionMode("browser")}
              >
                <div className="flex items-center gap-2 text-white font-medium mb-2">
                  <MonitorPlay size={18} className="text-sky-400" />
                  Через браузер
                </div>
                <p className="text-xs text-slate-400">
                  Интерактивный вход в noVNC: 2FA, challenge и backup-коды вручную. Сессия сохраняется
                  для автопостинга.
                </p>
              </button>
            </div>
            <button
              type="button"
              className="text-xs text-slate-500 hover:text-slate-300 underline"
              onClick={() => setConnectionMode("manual")}
            >
              Другой способ: вставить sessionid вручную
            </button>
          </div>
        ) : connectionMode === "auto" ? (
          <div className="space-y-3 text-sm">
            <ol className="list-decimal list-inside space-y-2 text-slate-300">
              <li>Убедитесь, что прокси назначен и Instagram доступен.</li>
              <li>Нажмите «Создать сессию» — сервер выполнит вход через Playwright Chromium.</li>
              <li>Если на аккаунте включена 2FA, укажите TOTP seed в настройках аккаунта.</li>
              <li>После успеха sessionid сохранится в БД (без mobile-проверки).</li>
            </ol>
            <p className="text-xs text-slate-400">
              Если входите по email или телефону, укажите это в настройках аккаунта в поле «Логин
              Instagram».
            </p>
            {firstLoginResult?.challenge ? (
              <div className="rounded-lg border border-amber-500/50 bg-amber-950/40 p-3 text-xs text-amber-100">
                Instagram запросил подтверждение.{" "}
                <button
                  type="button"
                  className="underline hover:text-amber-50"
                  onClick={() => setConnectionMode("browser")}
                >
                  Перейти к входу через браузер
                </button>
              </div>
            ) : null}
          </div>
        ) : connectionMode === "browser" ? (
          account ? (
            <InstagramBrowserPanel
              username={account.username}
              adminToken={adminToken}
              mode="setup"
              loginSurface={loginSurface}
              onSessionSaved={handleBrowserSessionSaved}
            />
          ) : null
        ) : (
          <div className="space-y-4">
            <ol className="list-decimal list-inside space-y-2 text-sm text-slate-300">
              <li>Откройте Dolphin Anty (или браузер) с тем же прокси, что у аккаунта.</li>
              <li>Войдите в Instagram и пройдите challenge при необходимости.</li>
              <li>Скопируйте cookie <span className="font-mono text-xs">sessionid</span> из DevTools.</li>
              <li>Вставьте ниже и нажмите «Сохранить сессию».</li>
            </ol>
            <form id="session-setup-manual-form" onSubmit={submitManual} className="space-y-3">
              <div>
                <label className="label" htmlFor="session-setup-id">
                  cookie sessionid
                </label>
                <textarea
                  id="session-setup-id"
                  className="input min-h-[88px] font-mono text-xs"
                  value={sessionId}
                  onChange={(e) => setSessionId(e.target.value)}
                  placeholder="Вставьте sessionid из Dolphin / devtools браузера"
                  autoComplete="off"
                  spellCheck={false}
                />
              </div>
            </form>
          </div>
        )}

        {success ? (
          <div className="rounded-xl border border-emerald-800/60 bg-emerald-950/30 p-3 text-sm text-emerald-200">
            <div className="font-medium">
              Сессия сохранена · @{account?.username}
            </div>
            {(connectionResult ?? firstLoginResult?.connection_test)?.instagram_auth.ig_username ? (
              <div className="mt-1 text-xs opacity-90">
                Вход как @
                {(connectionResult ?? firstLoginResult?.connection_test)?.instagram_auth.ig_username}
              </div>
            ) : null}
            {connectionMode === "browser" ? (
              <div className="mt-1 text-xs opacity-90">
                Та же сессия будет использоваться для автопостинга и повторного автовхода.
              </div>
            ) : null}
          </div>
        ) : null}

        {(autoBusy || manualBusy || logs.length > 0) && (
          <div className="space-y-2">
            <div className="text-xs font-medium text-slate-400 uppercase tracking-wide">Лог</div>
            <DiagnosticLogPanel
              lines={logs}
              emptyLabel={autoBusy || manualBusy ? "Выполняется…" : "Лог появится после действия"}
              maxHeightClass="max-h-48"
            />
          </div>
        )}

        {firstLoginResult?.login_debug_available && loginDebugUrl ? (
          <div className="space-y-2">
            <div className="text-xs font-medium text-slate-400 uppercase tracking-wide">
              Скриншот браузера при ошибке
            </div>
            <div className="rounded-lg border border-slate-700 bg-slate-950/50 p-2 overflow-auto max-h-80">
              <img
                src={loginDebugUrl}
                alt="Скриншот страницы Instagram при ошибке входа"
                className="w-full h-auto rounded border border-slate-800"
              />
            </div>
          </div>
        ) : null}

        {!success && !autoBusy && connectionMode === "manual" && (
          <div className="space-y-2">
            <p className="text-xs text-amber-200/90">
              «Проверить подключение» гоняет sessionid через мобильный API Instagram и
              иногда инвалидирует web-cookie. Для экспорта в Dolphin лучше не проверять
              сразу после сохранения.
            </p>
            <button
              type="button"
              className="btn-ghost text-xs"
              disabled={manualBusy}
              onClick={async () => {
                if (!account) return;
                setManualBusy(true);
                try {
                  const test = await api.accounts.testConnection(account.username, {
                    probeMobile: false,
                  });
                  setConnectionResult(test);
                } catch (err) {
                  push((err as Error).message, "error");
                } finally {
                  setManualBusy(false);
                }
              }}
            >
              <RefreshCw size={14} className={manualBusy ? "animate-spin" : ""} />
              Только проверить подключение
            </button>
          </div>
        )}
      </div>
    </Modal>
  );
}
