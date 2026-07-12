import { CheckCircle2, KeyRound, RefreshCw, Sparkles, XCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { api, formatApiError } from "../api/client";
import type {
  AccountConnectionTestOut,
  AccountOut,
  AccountSessionUpdate,
  FirstLoginOut,
  InstagramAuthStepOut,
} from "../api/types";
import { DiagnosticLogPanel } from "./DiagnosticLogPanel";
import { Modal } from "./Modal";
import { useToast } from "../context/ToastContext";

type Tab = "auto" | "manual";

interface Props {
  account: AccountOut | null;
  open: boolean;
  onClose: () => void;
  onCompleted: () => void | Promise<void>;
}

export function isSessionMissing(auth: Pick<InstagramAuthStepOut, "error" | "error_code">): boolean {
  if (auth.error_code === "session_missing") return true;
  if (!auth.error) return false;
  const lower = auth.error.toLowerCase();
  return (
    lower.includes("session_id") ||
    auth.error.includes("файла сессии") ||
    auth.error.includes("нет файла сессии")
  );
}

export function SessionSetupModal({ account, open, onClose, onCompleted }: Props) {
  const { push } = useToast();
  const [tab, setTab] = useState<Tab>("auto");
  const [autoBusy, setAutoBusy] = useState(false);
  const [manualBusy, setManualBusy] = useState(false);
  const [sessionId, setSessionId] = useState("");
  const [firstLoginResult, setFirstLoginResult] = useState<FirstLoginOut | null>(null);
  const [connectionResult, setConnectionResult] = useState<AccountConnectionTestOut | null>(null);
  const [loginDebugUrl, setLoginDebugUrl] = useState<string | null>(null);
  const loginDebugUrlRef = useRef<string | null>(null);

  const success =
    firstLoginResult?.ok === true ||
    connectionResult?.overall_ok === true ||
    firstLoginResult?.connection_test?.overall_ok === true;

  useEffect(() => {
    if (!open) return;
    setTab("auto");
    setSessionId("");
    setFirstLoginResult(null);
    setConnectionResult(null);
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
    if (firstLoginResult?.challenge) {
      setTab("manual");
    }
  }, [firstLoginResult?.challenge]);

  async function runAutoLogin() {
    if (!account) return;
    setAutoBusy(true);
    setFirstLoginResult(null);
    setConnectionResult(null);
    try {
      const data = await api.accounts.firstLogin(account.username);
      setFirstLoginResult(data);
      if (data.connection_test) {
        setConnectionResult(data.connection_test);
      }
      if (data.ok) {
        push(`@${account.username}: сессия создана и проверена`, "success");
      } else if (data.challenge) {
        push("Требуется ручное подтверждение — используйте вкладку «Ручной импорт»", "error");
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
    const trimmed = sessionId.trim();
    if (trimmed.length < 31) {
      push("Вставьте корректную cookie sessionid (31+ символов)", "error");
      return;
    }
    setManualBusy(true);
    setConnectionResult(null);
    try {
      const payload: AccountSessionUpdate = { session_id: trimmed };
      await api.accounts.updateSession(account.username, payload);
      const test = await api.accounts.testConnection(account.username);
      setConnectionResult(test);
      if (test.overall_ok) {
        push(`@${account.username}: сессия сохранена и проверена`, "success");
      } else {
        push(test.instagram_auth.error ?? "Проверка сессии не пройдена", "error");
      }
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
    firstLoginResult?.logs ??
    connectionResult?.logs ??
    firstLoginResult?.connection_test?.logs ??
    [];

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Настройка сессии · @${account?.username ?? ""}`}
      widthClass="max-w-2xl"
      footer={
        <>
          <button type="button" onClick={onClose} className="btn-ghost">
            <XCircle size={16} /> Закрыть
          </button>
          {success ? (
            <button type="button" className="btn-primary" onClick={handleDone}>
              <CheckCircle2 size={16} /> Готово
            </button>
          ) : tab === "auto" ? (
            <button
              type="button"
              className="btn-primary"
              disabled={autoBusy || !account}
              onClick={runAutoLogin}
            >
              <Sparkles size={16} className={autoBusy ? "animate-spin" : ""} />
              {autoBusy ? "Создание сессии…" : "Создать сессию"}
            </button>
          ) : (
            <button
              form="session-setup-manual-form"
              type="submit"
              className="btn-primary"
              disabled={manualBusy}
            >
              <KeyRound size={16} />
              {manualBusy ? "Сохранение…" : "Сохранить и проверить"}
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

        <div className="flex gap-1 p-1 rounded-lg bg-slate-900/60 border border-slate-800">
          <button
            type="button"
            className={`flex-1 text-sm py-1.5 rounded-md ${
              tab === "auto" ? "bg-slate-800 text-white" : "text-slate-400 hover:text-slate-200"
            }`}
            onClick={() => setTab("auto")}
          >
            Автовход
          </button>
          <button
            type="button"
            className={`flex-1 text-sm py-1.5 rounded-md ${
              tab === "manual" ? "bg-slate-800 text-white" : "text-slate-400 hover:text-slate-200"
            }`}
            onClick={() => setTab("manual")}
          >
            Ручной импорт
          </button>
        </div>

        {tab === "auto" ? (
          <div className="space-y-3 text-sm">
            <ol className="list-decimal list-inside space-y-2 text-slate-300">
              <li>Убедитесь, что прокси назначен и Instagram доступен (шаги 1–3 проверки подключения).</li>
              <li>Нажмите «Создать сессию» — сервер выполнит вход через Playwright Chromium.</li>
              <li>Если на аккаунте включена 2FA, укажите TOTP seed в настройках аккаунта.</li>
              <li>После успеха sessionid сохранится в БД и запустится повторная проверка.</li>
            </ol>
            <p className="text-xs text-slate-400">
              Если входите по email или телефону, укажите это в настройках аккаунта в поле «Логин Instagram».
            </p>
            {firstLoginResult?.challenge ? (
              <div className="rounded-lg border border-amber-500/50 bg-amber-950/40 p-3 text-xs text-amber-100">
                Instagram запросил ручное подтверждение. Перейдите на вкладку «Ручной импорт» и вставьте
                sessionid из Dolphin или браузера после входа.
              </div>
            ) : null}
          </div>
        ) : (
          <div className="space-y-4">
            <ol className="list-decimal list-inside space-y-2 text-sm text-slate-300">
              <li>Откройте Dolphin Anty (или браузер) с тем же прокси, что у аккаунта.</li>
              <li>Войдите в Instagram и пройдите challenge при необходимости.</li>
              <li>Скопируйте cookie <span className="font-mono text-xs">sessionid</span> из DevTools.</li>
              <li>Вставьте ниже и нажмите «Сохранить и проверить».</li>
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
              Сессия создана · @{account?.username} подтверждён
            </div>
            {(connectionResult ?? firstLoginResult?.connection_test)?.instagram_auth.ig_username ? (
              <div className="mt-1 text-xs opacity-90">
                Вход как @
                {(connectionResult ?? firstLoginResult?.connection_test)?.instagram_auth.ig_username}
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

        {!success && !autoBusy && tab === "manual" && (
          <button
            type="button"
            className="btn-ghost text-xs"
            disabled={manualBusy}
            onClick={async () => {
              if (!account) return;
              setManualBusy(true);
              try {
                const test = await api.accounts.testConnection(account.username);
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
        )}
      </div>
    </Modal>
  );
}
