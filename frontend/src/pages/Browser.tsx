import { MonitorPlay } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { api, formatApiError } from "../api/client";
import type { AccountOut, LoginSurface } from "../api/types";
import { EmptyState } from "../components/EmptyState";
import { LazyInstagramBrowserPanel } from "../components/LazyInstagramBrowserPanel";
import { Loader } from "../components/Loader";
import { PageHeader } from "../components/PageHeader";
import { PageShell } from "../components/PageShell";
import { PlatformIcon, platformLabel } from "../components/PlatformIcon";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";

const LS_KEY = "insta.browserPage.lastUsername";

type PlatformFilter = "all" | "instagram" | "youtube" | "tiktok";

function accountPlatform(a: AccountOut): string {
  return (a.platform || "instagram").toLowerCase();
}

function matchesFilter(a: AccountOut, filter: PlatformFilter): boolean {
  if (filter === "all") return true;
  return accountPlatform(a) === filter;
}

export function Browser() {
  const { push } = useToast();
  const { state: authState } = useAuth();
  const adminToken = authState.state === "authed" ? authState.token : null;
  const [searchParams, setSearchParams] = useSearchParams();
  const [accounts, setAccounts] = useState<AccountOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [platformFilter, setPlatformFilter] = useState<PlatformFilter>("all");

  const usernameFromUrl = searchParams.get("username")?.trim() || "";
  const [selectedUsername, setSelectedUsername] = useState(usernameFromUrl);

  const loadAccounts = useCallback(async () => {
    setLoading(true);
    try {
      const rows = (await api.accounts.list()) ?? [];
      setAccounts(rows);
      setLoadError(null);
    } catch (err) {
      const message = formatApiError(err);
      setLoadError(message);
      push(message, "error");
    } finally {
      setLoading(false);
    }
  }, [push]);

  useEffect(() => {
    void loadAccounts();
  }, [loadAccounts]);

  const filteredAccounts = useMemo(
    () => accounts.filter((a) => matchesFilter(a, platformFilter)),
    [accounts, platformFilter]
  );

  useEffect(() => {
    if (!accounts.length) return;
    const fromUrl = usernameFromUrl;
    const fromLs = typeof localStorage !== "undefined" ? localStorage.getItem(LS_KEY) || "" : "";
    const pick = fromUrl || fromLs;
    if (pick && accounts.some((a) => a.username === pick)) {
      setSelectedUsername(pick);
      if (fromUrl !== pick) {
        setSearchParams({ username: pick }, { replace: true });
      }
      return;
    }
    if (!selectedUsername && filteredAccounts.length) {
      const first = filteredAccounts[0]!.username;
      setSelectedUsername(first);
      setSearchParams({ username: first }, { replace: true });
    }
  }, [accounts, filteredAccounts, usernameFromUrl, setSearchParams, selectedUsername]);

  const selected = useMemo(
    () => accounts.find((a) => a.username === selectedUsername) ?? null,
    [accounts, selectedUsername]
  );

  const selectAccount = (username: string) => {
    setSelectedUsername(username);
    setSearchParams({ username }, { replace: true });
    try {
      localStorage.setItem(LS_KEY, username);
    } catch {
      /* ignore */
    }
  };

  const panelPlatform =
    selected?.platform === "youtube" || selected?.platform === "tiktok"
      ? selected.platform
      : "instagram";

  const loginSurface: LoginSurface =
    selected?.login_surface === "desktop" ? "desktop" : "mobile";

  if (loading && !accounts.length) {
    return (
      <PageShell>
        <PageHeader
          icon={MonitorPlay}
          title="Браузер"
          description="noVNC Chrome / Studio — отдельная вкладка для входа и сохранения сессии."
        />
        <Loader label="Загрузка аккаунтов…" />
      </PageShell>
    );
  }

  return (
    <PageShell error={loadError} onRetry={() => void loadAccounts()}>
      <PageHeader
        icon={MonitorPlay}
        title="Браузер"
        description="Запуск Chrome (native VNC) для YouTube/TikTok Studio или Instagram без модального окна в карточке."
      />

      <div className="flex flex-col gap-4 lg:flex-row lg:items-start">
        <aside className="card w-full shrink-0 space-y-3 p-4 lg:w-72">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Площадка</p>
          <div className="flex flex-wrap gap-2">
            {(
              [
                ["all", "Все"],
                ["youtube", "YouTube"],
                ["tiktok", "TikTok"],
                ["instagram", "Instagram"],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                className={platformFilter === value ? "btn-primary text-xs py-1.5" : "btn-ghost text-xs py-1.5"}
                onClick={() => setPlatformFilter(value)}
              >
                {label}
              </button>
            ))}
          </div>

          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Аккаунт</p>
          {filteredAccounts.length === 0 ? (
            <p className="text-sm text-slate-400">Нет аккаунтов для выбранного фильтра.</p>
          ) : (
            <ul className="max-h-[min(50vh,28rem)] space-y-1 overflow-y-auto">
              {filteredAccounts.map((a) => {
                const active = a.username === selectedUsername;
                const hasProxy = Boolean(a.proxy_label);
                return (
                  <li key={`${a.platform}:${a.username}`}>
                    <button
                      type="button"
                      className={
                        active
                          ? "flex w-full items-center gap-2 rounded-lg bg-slate-800/80 px-3 py-2 text-left text-sm"
                          : "flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm hover:bg-slate-800/40"
                      }
                      onClick={() => selectAccount(a.username)}
                    >
                      <PlatformIcon platform={a.platform} className="shrink-0" />
                      <span className="min-w-0 flex-1 truncate">@{a.username}</span>
                      {!hasProxy ? (
                        <span className="text-[10px] uppercase text-amber-400/90">нет прокси</span>
                      ) : null}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
          {selected ? (
            <p className="text-xs text-slate-500">
              {platformLabel(selected.platform)}
              {selected.proxy_label ? ` · ${selected.proxy_label}` : " · прокси не задан"}
            </p>
          ) : null}
        </aside>

        <div className="min-w-0 flex-1">
          {!selected ? (
            <EmptyState title="Выберите аккаунт">
              Список слева — запуск VNC привязан к аккаунту и его прокси.
            </EmptyState>
          ) : !selected.proxy_label ? (
            <EmptyState title="Нужен прокси">
              Назначьте прокси в карточке аккаунта на странице «Аккаунты», затем вернитесь сюда.
            </EmptyState>
          ) : (
            <LazyInstagramBrowserPanel
              key={`${selected.platform}:${selected.username}`}
              username={selected.username}
              adminToken={adminToken}
              platform={panelPlatform}
              hasProxy={Boolean(selected.proxy_label)}
              loginSurface={loginSurface}
              mode="standalone"
            />
          )}
        </div>
      </div>
    </PageShell>
  );
}
