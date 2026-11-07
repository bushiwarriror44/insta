import { Loader2, Play, Square } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { api, formatApiError } from "../api/client";
import type { BrowserSessionOut, ProxyOut } from "../api/types";
import { usePollWhenVisible } from "../hooks/usePollWhenVisible";
import { useToast } from "../context/ToastContext";
import { BrowserVncFrame } from "./BrowserVncFrame";
import { StatusBadge } from "./StatusBadge";

const LS_PROXY = "insta.browserPage.lastFreeProxy";

type Props = {
  adminToken: string | null;
};

export function FreeBrowserPanel({ adminToken }: Props) {
  const { push } = useToast();
  const [proxies, setProxies] = useState<ProxyOut[]>([]);
  const [proxyLabel, setProxyLabel] = useState("");
  const [initialUrl, setInitialUrl] = useState("https://www.google.com");
  const [session, setSession] = useState<BrowserSessionOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [loadingProxies, setLoadingProxies] = useState(true);

  const selectedProxy = useMemo(
    () => proxies.find((p) => p.label === proxyLabel) ?? null,
    [proxies, proxyLabel]
  );

  const loadProxies = useCallback(async () => {
    setLoadingProxies(true);
    try {
      const rows = (await api.proxies.list()) ?? [];
      setProxies(rows);
      const fromLs = localStorage.getItem(LS_PROXY) || "";
      const pick = rows.find((p) => p.label === fromLs)?.label ?? rows[0]?.label ?? "";
      setProxyLabel((cur) => cur || pick);
    } catch (err) {
      push(formatApiError(err), "error");
    } finally {
      setLoadingProxies(false);
    }
  }, [push]);

  useEffect(() => {
    void loadProxies();
  }, [loadProxies]);

  const refreshStatus = useCallback(async () => {
    if (!session?.username?.startsWith("adhoc-")) return;
    try {
      const data = await api.browserFree.status(session.username);
      setSession(data);
    } catch {
      /* session may have ended */
    }
  }, [session?.username]);

  usePollWhenVisible(
    refreshStatus,
    2500,
    Boolean(session?.username?.startsWith("adhoc-") && session.status === "running")
  );

  const pickProxy = (label: string) => {
    setProxyLabel(label);
    try {
      localStorage.setItem(LS_PROXY, label);
    } catch {
      /* ignore */
    }
  };

  async function start() {
    if (!proxyLabel) {
      push("Выберите прокси", "error");
      return;
    }
    setBusy(true);
    try {
      const data = await api.browserFree.start({
        proxy_label: proxyLabel,
        initial_url: initialUrl.trim() || "https://www.google.com",
      });
      setSession(data);
      push("Свободный браузер запущен", "success");
    } catch (err) {
      push(formatApiError(err), "error");
    } finally {
      setBusy(false);
    }
  }

  async function stop() {
    if (!session?.username?.startsWith("adhoc-")) return;
    setBusy(true);
    try {
      const data = await api.browserFree.stop(session.username);
      setSession(data);
      push("Браузер остановлен", "success");
    } catch (err) {
      push(formatApiError(err), "error");
    } finally {
      setBusy(false);
    }
  }

  const running = session?.status === "running" || session?.status === "starting";

  return (
    <div className="space-y-4" data-testid="free-browser-panel">
      <div className="card p-4 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-medium text-slate-200">Свободный Chrome</h2>
          {session?.status ? <StatusBadge value={session.status} /> : null}
        </div>
        <p className="text-xs text-slate-500">
          Без привязки к аккаунту. Профиль хранится отдельно; сессию аккаунта не сохраняем.
        </p>

        <label className="block space-y-1 text-xs text-slate-400">
          Прокси
          {loadingProxies ? (
            <span className="text-slate-600"> загрузка…</span>
          ) : (
            <select
              className="input w-full mt-1"
              value={proxyLabel}
              onChange={(e) => pickProxy(e.target.value)}
              disabled={busy || running}
              data-testid="free-browser-proxy"
            >
              <option value="">— выберите —</option>
              {proxies.map((p) => (
                <option key={p.id} value={p.label}>
                  {p.label}
                  {p.country ? ` · ${p.country}` : ""}
                  {p.is_healthy === false ? " (проверка?)" : ""}
                </option>
              ))}
            </select>
          )}
        </label>

        {selectedProxy && !selectedProxy.is_healthy ? (
          <p className="text-xs text-amber-300">Прокси помечен как проблемный — запуск может не удаться.</p>
        ) : null}

        <label className="block space-y-1 text-xs text-slate-400">
          Стартовая страница
          <input
            className="input w-full mt-1 font-mono text-xs"
            value={initialUrl}
            onChange={(e) => setInitialUrl(e.target.value)}
            disabled={busy || running}
            placeholder="https://www.google.com"
          />
        </label>

        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="btn-primary"
            disabled={busy || running || !proxyLabel}
            onClick={() => void start()}
            data-testid="free-browser-start"
          >
            {busy ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
            Старт
          </button>
          <button
            type="button"
            className="btn-ghost text-rose-300"
            disabled={busy || !session?.username?.startsWith("adhoc-")}
            onClick={() => void stop()}
          >
            <Square size={16} /> Стоп
          </button>
        </div>

        {session?.proxy_ip ? (
          <p className="text-xs text-slate-500">
            IP прокси: <span className="font-mono text-slate-300">{session.proxy_ip}</span>
          </p>
        ) : null}
        {session?.error ? <p className="text-xs text-rose-300">{session.error}</p> : null}
        {session?.warning ? <p className="text-xs text-amber-300">{session.warning}</p> : null}
      </div>

      <BrowserVncFrame
        session={session}
        adminToken={adminToken}
        iframeTitle="Свободный VNC"
        placeholder="Нажмите «Старт» — откроется Chrome через выбранный прокси"
      />
    </div>
  );
}
