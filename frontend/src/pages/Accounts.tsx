import {
  CheckCircle2,
  Copy,
  Download,
  ExternalLink,
  KeyRound,
  MonitorPlay,
  Network,
  Pencil,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Server,
  ShieldOff,
  Sparkles,
  Trash2,
  Users,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { api, formatApiError } from "../api/client";
import { Card } from "../components/Card";
import { CountryFlag, countryCodeToFlag } from "../components/CountryFlag";
import { DiagnosticLogPanel, copyTextToClipboard } from "../components/DiagnosticLogPanel";
import { EmptyState } from "../components/EmptyState";
import { Loader } from "../components/Loader";
import { Modal } from "../components/Modal";
import { PageHeader } from "../components/PageHeader";
import {
  isSessionExpired,
  isSessionMissing,
  SESSION_EXPIRED_MOBILE_HINT,
  SessionSetupModal,
} from "../components/SessionSetupModal";
import { FloppydataProxyPanel } from "../components/FloppydataProxyPanel";
import { InstagramBrowserPanel } from "../components/InstagramBrowserPanel";
import { StatusBadge } from "../components/StatusBadge";
import { useAuth } from "../context/AuthContext";

type AccountsMainTab = "accounts" | "proxies" | "floppydata";
import { useToast } from "../context/ToastContext";
import { usePollWhenVisible } from "../hooks/usePollWhenVisible";
import { useAssistantMutate } from "../lib/assistantMutate";
import type {
  AccountConnectionTestOut,
  AccountIn,
  AccountOut,
  AccountProxyUpdate,
  AccountSessionOut,
  AccountSessionUpdate,
  DiagnosticRunOut,
  ProxyIn,
  ProxyOut,
  ProxyUpdate,
} from "../api/types";
import { CAPTION_PROFILE_OPTIONS } from "../api/types";

const POLL_INTERVAL_MS = 10000;

function proxyOptionLabel(p: ProxyOut): string {
  const flag = countryCodeToFlag(p.country);
  const prefix = flag ? `${flag} ` : "";
  return `${prefix}${p.label}${p.country ? ` (${p.country})` : ""}`;
}

function isInstagram(account: AccountOut | null | undefined): boolean {
  return (account?.platform || "instagram") === "instagram";
}

function sessionSourceLabel(source: AccountOut["session_source"]): string {
  if (source === "database") return "sessionid в БД";
  if (source === "session_file") return "Файл cookies";
  if (source === "playwright") return "Состояние Playwright";
  return "Нет сессии";
}

type StepVisual = "pending" | "running" | "ok" | "warn" | "fail";

function ConnectionStepRow({
  label,
  state,
  detail,
}: {
  label: string;
  state: StepVisual;
  detail?: React.ReactNode;
}) {
  const dot =
    state === "ok"
      ? "bg-emerald-500"
      : state === "warn"
        ? "bg-amber-400"
        : state === "fail"
          ? "bg-rose-500"
          : state === "running"
            ? "bg-brand-400 animate-pulse"
            : "bg-slate-600";
  return (
    <div className="flex gap-3 items-start rounded-lg border border-slate-800 bg-slate-950/40 p-3">
      <span className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${dot}`} />
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium text-slate-200">{label}</div>
        {detail ? <div className="mt-1 text-xs text-slate-400">{detail}</div> : null}
      </div>
    </div>
  );
}

function RowIconButton({
  label,
  onClick,
  disabled,
  title,
  danger,
  children,
}: {
  label: string;
  onClick: () => void | Promise<void>;
  disabled?: boolean;
  title?: string;
  danger?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      className={`btn-ghost btn-compact ${danger ? "text-rose-300 disabled:opacity-40" : ""}`}
      aria-label={label}
      title={title ?? label}
      disabled={disabled}
      onClick={() => void onClick()}
    >
      {children}
    </button>
  );
}

export function Accounts() {
  const { push } = useToast();
  const { state: authState } = useAuth();
  const adminToken = authState.state === "authed" ? authState.token : null;
  const [accounts, setAccounts] = useState<AccountOut[]>([]);
  const [proxies, setProxies] = useState<ProxyOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [openAccount, setOpenAccount] = useState(false);
  const [openProxy, setOpenProxy] = useState(false);
  const [editingProxy, setEditingProxy] = useState<ProxyOut | null>(null);
  const [assigningAccount, setAssigningAccount] = useState<AccountOut | null>(null);
  const [sessionAccount, setSessionAccount] = useState<AccountOut | null>(null);
  const [sessionSetupAccount, setSessionSetupAccount] = useState<AccountOut | null>(null);
  const [browserAccount, setBrowserAccount] = useState<AccountOut | null>(null);
  const [connectionAccount, setConnectionAccount] = useState<AccountOut | null>(null);
  const [testingAll, setTestingAll] = useState(false);
  const [testAllProgress, setTestAllProgress] = useState({ done: 0, total: 0, ok: 0 });
  const [flashAccountIds, setFlashAccountIds] = useState<number[]>([]);
  const [flashProxyIds, setFlashProxyIds] = useState<number[]>([]);
  const [accountQuery, setAccountQuery] = useState("");
  const downloadStarted = useRef<string | null>(null);
  const loadingRef = useRef(true);
  const [searchParams, setSearchParams] = useSearchParams();
  const askedId = Number(searchParams.get("id") || 0);
  const askedUser = searchParams.get("username");
  const askedQ = searchParams.get("q");
  const statusFromUrl = (() => {
    const raw = searchParams.get("status") || "";
    return ["active", "paused", "challenge", "cooldown", "blocked"].includes(raw) ? raw : "";
  })();
  const proxyFromUrl = (() => {
    const raw = searchParams.get("proxy") || "";
    return raw === "bad" || raw === "ok" ? raw : "";
  })();
  const [mainTab, setMainTab] = useState<AccountsMainTab>(() =>
    proxyFromUrl ? "proxies" : "accounts"
  );
  const download = searchParams.get("download");
  const downloadFormat = searchParams.get("format") === "txt" ? "txt" : "json";

  const reload = useCallback(async () => {
    const [a, p] = await Promise.all([api.accounts.list(), api.proxies.list()]);
    setAccounts(a);
    setProxies(p);
  }, []);

  useEffect(() => {
    if (askedQ) setAccountQuery(askedQ);
    else if (askedUser) setAccountQuery(askedUser);
  }, [askedQ, askedUser]);

  const [statusFilter, setStatusFilterState] = useState(statusFromUrl);
  useEffect(() => {
    setStatusFilterState(statusFromUrl);
  }, [statusFromUrl]);
  const setStatusFilter = useCallback(
    (next: string) => {
      setStatusFilterState(next);
      setSearchParams(
        (prev) => {
          const params = new URLSearchParams(prev);
          if (next) params.set("status", next);
          else params.delete("status");
          return params;
        },
        { replace: true }
      );
    },
    [setSearchParams]
  );
  const [proxyFilter, setProxyFilterState] = useState(proxyFromUrl);
  useEffect(() => {
    setProxyFilterState(proxyFromUrl);
  }, [proxyFromUrl]);
  const setProxyFilter = useCallback(
    (next: string) => {
      setProxyFilterState(next);
      setSearchParams(
        (prev) => {
          const params = new URLSearchParams(prev);
          if (next) params.set("proxy", next);
          else params.delete("proxy");
          return params;
        },
        { replace: true }
      );
    },
    [setSearchParams]
  );
  const shownAccounts = useMemo(() => {
    const needle = accountQuery.trim().toLowerCase();
    return accounts.filter((a) => {
      if (statusFilter && a.status !== statusFilter) return false;
      if (!needle) return true;
      const hay = `${a.username} ${a.platform || ""} ${a.status} ${a.proxy_label ?? ""}`.toLowerCase();
      return hay.includes(needle);
    });
  }, [accountQuery, accounts, statusFilter]);
  const shownProxies = useMemo(() => {
    if (!proxyFilter) return proxies;
    return proxies.filter((p) => (proxyFilter === "ok" ? p.is_healthy : !p.is_healthy));
  }, [proxies, proxyFilter]);
  useEffect(() => {
    if (!proxyFilter) return;
    document.getElementById("proxies-card")?.scrollIntoView?.({ block: "start" });
  }, [proxyFilter, proxies.length, shownProxies.length]);

  useAssistantMutate(async (detail) => {
    await reload();
    setFlashAccountIds(detail?.accounts ?? []);
    setFlashProxyIds(detail?.proxies ?? []);
  });

  const tick = useCallback(async () => {
    try {
      await reload();
    } catch (err) {
      if (loadingRef.current) push((err as Error).message, "error");
    } finally {
      loadingRef.current = false;
      setLoading(false);
    }
  }, [push, reload]);
  usePollWhenVisible(tick, POLL_INTERVAL_MS);

  useEffect(() => {
    const byName = askedUser
      ? accounts.find((a) => a.username === askedUser)?.id
      : 0;
    const target = askedId || byName;
    if (!target || !accounts.some((a) => a.id === target)) return;
    setFlashAccountIds((ids) => (ids.includes(target) ? ids : [target, ...ids]));
  }, [accounts, askedId, askedUser]);

  useEffect(() => {
    const byName = askedUser
      ? accounts.find((a) => a.username === askedUser)?.id
      : 0;
    const scrollAccount = flashAccountIds[0] || askedId || byName;
    if (scrollAccount) {
      document.getElementById(`account-${scrollAccount}`)?.scrollIntoView?.({ block: "center" });
    } else if (flashProxyIds[0]) {
      document.getElementById(`proxy-${flashProxyIds[0]}`)?.scrollIntoView?.({ block: "center" });
    }
  }, [accounts, flashAccountIds, flashProxyIds, askedId, askedUser]);

  useEffect(() => {
    if (!download || !askedId || accounts.length === 0) return;
    const account = accounts.find((a) => a.id === askedId);
    if (!account) return;
    const key = `${askedId}:${download}:${downloadFormat}`;
    if (downloadStarted.current === key) return;
    downloadStarted.current = key;
    void (async () => {
      try {
        if (download === "cookies") {
          await api.accounts.exportCookies(account.username, downloadFormat);
        } else if (download === "fingerprint") {
          await api.accounts.exportDeviceFingerprint(account.username, downloadFormat);
        } else if (download === "playwright") {
          await api.accounts.exportPlaywrightState(account.username, downloadFormat);
        } else {
          downloadStarted.current = null;
          return;
        }
        push("Файл скачан", "success");
      } catch (err) {
        push((err as Error).message, "error");
      } finally {
        const next = new URLSearchParams(window.location.search);
        next.delete("download");
        next.delete("format");
        const qs = next.toString();
        window.history.replaceState(
          null,
          "",
          `${window.location.pathname}${qs ? `?${qs}` : ""}${window.location.hash}`
        );
      }
    })();
  }, [accounts, askedId, download, downloadFormat, push]);

  const onCreatedAccount = async () => {
    setOpenAccount(false);
    await reload();
    push("Аккаунт сохранён", "success");
  };
  const onCreatedProxy = async () => {
    setOpenProxy(false);
    await reload();
    push("Прокси сохранён", "success");
  };
  const onUpdatedProxy = async () => {
    setEditingProxy(null);
    await reload();
    push("Прокси обновлён", "success");
  };
  const onAssignedProxy = async () => {
    setAssigningAccount(null);
    await reload();
    push("Прокси аккаунта обновлён", "success");
  };
  const onImportedSession = async () => {
    // Keep SessionModal open after import; refresh list so has_session_id updates.
    await reload();
    if (sessionAccount) {
      const refreshed = await api.accounts.list().catch(() => null);
      if (refreshed) {
        const next = refreshed.find((a) => a.username === sessionAccount.username);
        if (next) setSessionAccount(next);
      }
    }
    push("Сессия сохранена", "success");
  };
  const onBrowserSessionSaved = async () => {
    await reload();
    if (browserAccount) {
      const refreshed = await api.accounts.list().catch(() => null);
      if (refreshed) {
        const next = refreshed.find((a) => a.username === browserAccount.username);
        if (next) setBrowserAccount(next);
      }
    }
  };
  const onSessionSetupCompleted = async () => {
    setSessionSetupAccount(null);
    await reload();
  };

  const testAllConnections = useCallback(async () => {
    const targets = accounts.filter((a) => a.proxy_label);
    if (targets.length === 0) {
      push("Нет аккаунтов с прокси для проверки", "error");
      return;
    }
    setTestingAll(true);
    setTestAllProgress({ done: 0, total: targets.length, ok: 0 });
    let okCount = 0;
    try {
      for (let i = 0; i < targets.length; i++) {
        const account = targets[i];
        try {
          const result = await api.accounts.testConnection(account.username);
          if (result.overall_ok) okCount += 1;
          if (result.proxy_label) {
            const label = result.proxy_label;
            setProxies((arr) =>
              arr.map((x) =>
                x.label === label
                  ? {
                      ...x,
                      is_healthy: result.proxy_health.ok,
                      last_known_ip: result.proxy_health.ip ?? x.last_known_ip,
                      last_geo_country:
                        result.proxy_health.geo_country ?? x.last_geo_country,
                      instagram_reachable: result.proxy_health.instagram_reachable,
                      geo_mismatch_warning: result.proxy_health.geo_mismatch,
                    }
                  : x
              )
            );
          }
          setAccounts((arr) =>
            arr.map((x) =>
              x.id === account.id
                ? {
                    ...x,
                    proxy_is_healthy: result.proxy_health.ok,
                    proxy_geo_country:
                      result.proxy_health.geo_country ?? x.proxy_geo_country,
                    proxy_last_ip: result.proxy_health.ip ?? x.proxy_last_ip,
                    session_file_exists: result.session_storage.session_file_exists,
                    session_source: result.session_storage.session_source,
                  }
                : x
            )
          );
        } catch (err) {
          push(`@${account.username}: ${(err as Error).message}`, "error");
        }
        setTestAllProgress({ done: i + 1, total: targets.length, ok: okCount });
      }
      push(
        `Проверено ${targets.length} акк.: ${okCount} с cookies`,
        okCount === targets.length ? "success" : "info"
      );
    } finally {
      setTestingAll(false);
    }
  }, [accounts, push]);

  if (loading) return <Loader />;

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <PageHeader
          icon={Users}
          title="Аккаунты"
          description="Аккаунты Instagram, YouTube и TikTok и их прокси."
        />
        <div className="flex items-center gap-2">
          {mainTab === "proxies" ? (
            <button className="btn-ghost" onClick={() => setOpenProxy(true)}>
              <Server size={16} />
              <span>Добавить прокси</span>
            </button>
          ) : null}
          {mainTab === "accounts" ? (
            <button className="btn-primary" onClick={() => setOpenAccount(true)}>
              <Plus size={16} />
              <span>Добавить аккаунт</span>
            </button>
          ) : null}
        </div>
      </div>

      <div
        className="flex flex-wrap items-center gap-1 border-b border-slate-800 pb-1"
        role="tablist"
        aria-label="Разделы аккаунтов"
      >
        {(
          [
            ["accounts", "Аккаунты"],
            ["proxies", "Прокси"],
            ["floppydata", "Floppydata прокси"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={mainTab === id}
            data-testid={`accounts-tab-${id}`}
            className={
              mainTab === id
                ? "rounded-t-lg bg-slate-900 px-3 py-1.5 text-xs text-slate-100 ring-1 ring-slate-700/80"
                : "rounded-t-lg px-3 py-1.5 text-xs text-slate-500 hover:bg-slate-900/60 hover:text-slate-300"
            }
            onClick={() => setMainTab(id)}
          >
            {label}
          </button>
        ))}
      </div>

      {mainTab === "proxies" ? (
      <Card
        id="proxies-card"
        title="Прокси"
        description={
          proxyFilter
            ? `${shownProxies.length} из ${proxies.length}`
            : `${proxies.length} настроено`
        }
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {(
              [
                ["", "Все"],
                ["ok", "Исправные"],
                ["bad", "Недоступные"],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value || "all"}
                type="button"
                aria-pressed={proxyFilter === value}
                aria-label={`Фильтр прокси: ${label}`}
                className={
                  proxyFilter === value
                    ? "rounded-full bg-brand-600/20 px-2 py-0.5 text-xs text-brand-200 ring-1 ring-brand-500/40"
                    : "rounded-full px-2 py-0.5 text-xs text-slate-400 ring-1 ring-slate-700 hover:bg-slate-800/60"
                }
                onClick={() => setProxyFilter(value)}
              >
                {label}
              </button>
            ))}
            <button
              className="btn-ghost text-xs"
              onClick={async () => {
                try {
                  await reload();
                  push("Обновлено", "info");
                } catch (err) {
                  push((err as Error).message, "error");
                }
              }}
            >
              <RefreshCw size={14} />
              Обновить
            </button>
          </div>
        }
      >
        {proxies.length === 0 ? (
          <EmptyState>Прокси пока нет.</EmptyState>
        ) : shownProxies.length === 0 ? (
          <EmptyState>
            {proxyFilter === "bad" ? "Недоступных прокси нет." : "Нет прокси с этим фильтром."}
          </EmptyState>
        ) : (
          <div className="table-scroll">
          <table className="table-base">
            <colgroup>
              <col className="w-[16%]" />
              <col className="w-[28%]" />
              <col className="w-[24%]" />
              <col className="w-[10%]" />
              <col className="w-[22%]" />
            </colgroup>
            <thead>
              <tr>
                <th>Метка</th>
                <th className="hidden md:table-cell">URL</th>
                <th className="hidden sm:table-cell">Страна / IP</th>
                <th>Статус</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {shownProxies.map((p) => (
                <tr
                  id={`proxy-${p.id}`}
                  key={p.id}
                  className={`hover:bg-slate-900/40 ${flashProxyIds.includes(p.id) ? "flash-row" : ""}`}
                >
                  <td className="font-medium">
                    <div className="truncate" title={p.label}>
                      {p.label}
                    </div>
                    <div className="text-[11px] text-slate-500 tabular-nums">
                      {p.accounts_count ?? 0} акк.
                    </div>
                  </td>
                  <td className="hidden min-w-0 truncate font-mono text-[11px] text-slate-400 md:table-cell" title={p.url}>
                    {p.url}
                  </td>
                  <td
                    className="hidden min-w-0 text-slate-400 sm:table-cell"
                    title={
                      p.geo_mismatch_warning
                        ? `Не совпадает с заявленной страной (${p.country})`
                        : undefined
                    }
                  >
                    <div className="truncate">
                      <span className="inline-flex items-center gap-1">
                        <CountryFlag code={p.country} />
                        {p.country ?? "—"}
                        {p.timezone ? ` · ${p.timezone}` : ""}
                      </span>
                    </div>
                    <div className="truncate font-mono text-[11px] text-slate-300 tabular-nums">
                      {p.last_known_ip ?? "—"}
                    </div>
                    <span
                      className={
                        p.geo_mismatch_warning
                          ? "inline-flex items-center gap-1 text-amber-300"
                          : "inline-flex items-center gap-1 text-slate-400"
                      }
                    >
                      <CountryFlag code={p.last_geo_country} />
                      {p.last_geo_country ?? "—"}
                    </span>
                  </td>
                  <td>
                    <StatusBadge value={p.is_healthy ? "ok" : "bad"} />
                  </td>
                  <td className="text-right">
                    <div className="flex items-center justify-end gap-1 flex-wrap">
                      <RowIconButton
                        label={`Изменить прокси ${p.label}`}
                        onClick={() => setEditingProxy(p)}
                      >
                        <Pencil size={14} />
                      </RowIconButton>
                      <RowIconButton
                        label={`Удалить прокси ${p.label}`}
                        danger
                        disabled={(p.accounts_count ?? 0) > 0}
                        title={
                          (p.accounts_count ?? 0) > 0
                            ? `${p.accounts_count} акк. используют этот прокси — сначала переназначьте их`
                            : "Удалить этот прокси"
                        }
                        onClick={async () => {
                          if ((p.accounts_count ?? 0) > 0) return;
                          if (!window.confirm(`Удалить прокси «${p.label}» навсегда?`)) return;
                          try {
                            await api.proxies.remove(p.label);
                            await reload();
                            push(`Прокси ${p.label} удалён`, "info");
                          } catch (err) {
                            push((err as Error).message, "error");
                          }
                        }}
                      >
                        <Trash2 size={14} />
                      </RowIconButton>
                      <RowIconButton
                        label={`Проверка прокси ${p.label}`}
                        onClick={async () => {
                          try {
                            const updated = await api.proxies.check(p.label);
                            setProxies((arr) =>
                              arr.map((x) => (x.id === updated.id ? updated : x))
                            );
                            const detail = updated.check_detail?.trim();
                            if (updated.is_healthy && !detail) {
                              push(`Прокси ${p.label}: работает`, "success");
                            } else if (updated.is_healthy && detail) {
                              push(`Прокси ${p.label}: работает · ${detail}`, "success");
                            } else {
                              push(
                                detail
                                  ? `Прокси ${p.label}: ${detail}`
                                  : `Прокси ${p.label}: недоступен`,
                                "error"
                              );
                            }
                          } catch (err) {
                            push(formatApiError(err), "error");
                          }
                        }}
                      >
                        <RefreshCw size={14} />
                      </RowIconButton>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        )}
      </Card>
      ) : null}

      {mainTab === "floppydata" ? (
        <div className="card p-5">
          <FloppydataProxyPanel
            onImported={(imported) => {
              setProxies((arr) => {
                const byId = new Map(arr.map((p) => [p.id, p]));
                for (const p of imported) byId.set(p.id, p);
                return Array.from(byId.values()).sort((a, b) =>
                  a.label.localeCompare(b.label)
                );
              });
              setFlashProxyIds(imported.map((p) => p.id));
            }}
          />
        </div>
      ) : null}

      {mainTab === "accounts" ? (
      <Card
        title="Аккаунты"
        description={`${accounts.length} настроено`}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {(
              [
                ["", "Все"],
                ["active", "Активные"],
                ["paused", "Пауза"],
                ["challenge", "Проверка"],
                ["cooldown", "Карантин"],
                ["blocked", "Блок"],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value || "all"}
                type="button"
                aria-pressed={statusFilter === value}
                aria-label={`Фильтр статуса: ${label}`}
                className={
                  statusFilter === value
                    ? "rounded-full bg-brand-600/20 px-2 py-0.5 text-xs text-brand-200 ring-1 ring-brand-500/40"
                    : "rounded-full px-2 py-0.5 text-xs text-slate-400 ring-1 ring-slate-700 hover:bg-slate-800/60"
                }
                onClick={() => setStatusFilter(value)}
              >
                {label}
              </button>
            ))}
            <input
              className="input max-w-[12rem] py-1.5 text-xs"
              data-page-search
              aria-label="Поиск аккаунтов"
              placeholder="Имя, площадка, статус…"
              value={accountQuery}
              onChange={(e) => setAccountQuery(e.target.value)}
            />
            {accounts.length > 0 ? (
            <button
              type="button"
              className="btn-ghost text-xs"
              disabled={testingAll}
              onClick={testAllConnections}
            >
              <RefreshCw size={14} className={testingAll ? "animate-spin" : ""} />
              {testingAll
                ? `Проверка ${testAllProgress.done}/${testAllProgress.total}…`
                : "Проверить все"}
            </button>
            ) : null}
          </div>
        }
      >
        {accounts.length === 0 ? (
          <EmptyState>Аккаунтов пока нет.</EmptyState>
        ) : shownAccounts.length === 0 ? (
          <EmptyState>
            {statusFilter ? "Нет аккаунтов с этим статусом." : "Никого не нашлось."}
          </EmptyState>
        ) : (
          <div className="table-scroll">
          <table className="table-base">
            <colgroup>
              <col className="w-[22%]" />
              <col className="w-[14%]" />
              <col className="w-[18%]" />
              <col className="w-[24%]" />
              <col className="w-[22%]" />
            </colgroup>
            <thead>
              <tr>
                <th>Имя</th>
                <th className="hidden sm:table-cell">Площадка</th>
                <th className="hidden md:table-cell">Прокси</th>
                <th className="hidden lg:table-cell">Активность</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {shownAccounts.map((a) => {
                const lastPublish = a.last_publish_at
                  ? new Date(a.last_publish_at).toLocaleString()
                  : "—";
                const cooldown = a.cooldown_until
                  ? new Date(a.cooldown_until).toLocaleString()
                  : "—";
                return (
                  <tr
                    id={`account-${a.id}`}
                    key={a.id}
                    className={`hover:bg-slate-900/40 ${flashAccountIds.includes(a.id) ? "flash-row" : ""}`}
                  >
                    <td className="font-medium min-w-0">
                      <div className="truncate" title={`@${a.username}`}>
                        @{a.username}
                        {a.has_totp ? (
                          <span
                            className="ml-1 text-[10px] uppercase tracking-wide text-emerald-400"
                            title="Настроен секрет TOTP"
                          >
                            2FA
                          </span>
                        ) : null}
                        {isInstagram(a) && a.has_session_id ? (
                          <span
                            className="ml-1 text-[10px] uppercase tracking-wide text-brand-300"
                            title="Сессия сохранена — используется для автопостинга"
                          >
                            Сессия
                          </span>
                        ) : null}
                        {a.session_file_exists ? (
                          <span
                            className="ml-1 text-[10px] uppercase tracking-wide text-sky-300"
                            title={
                              a.session_file_updated_at
                                ? `Cookies на диске · ${new Date(a.session_file_updated_at).toLocaleString()}`
                                : "Cookies сохранены на диске"
                            }
                          >
                            Cookies
                          </span>
                        ) : null}
                      </div>
                      {a.caption_profile ? (
                        <div className="capitalize text-[11px] text-slate-400 truncate">
                          {a.caption_profile}
                        </div>
                      ) : null}
                      <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                        <a
                          href={
                            a.platform === "youtube"
                              ? `https://www.youtube.com/@${encodeURIComponent(a.username)}`
                              : a.platform === "tiktok"
                                ? `https://www.tiktok.com/@${encodeURIComponent(a.username)}`
                                : `https://www.instagram.com/${encodeURIComponent(a.username)}/`
                          }
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-1 text-[11px] font-normal text-brand-300 hover:text-brand-200"
                        >
                          <ExternalLink size={12} />
                          Профиль
                        </a>
                        <button
                          type="button"
                          className="inline-flex items-center gap-1 text-[11px] font-normal text-sky-300 hover:text-sky-200 disabled:opacity-40 disabled:pointer-events-none"
                          disabled={!a.proxy_label}
                          title={
                            a.proxy_label
                              ? "Открыть браузер через прокси аккаунта"
                              : "Сначала назначьте прокси"
                          }
                          onClick={() => setBrowserAccount(a)}
                        >
                          <MonitorPlay size={12} />
                          Браузер
                        </button>
                      </div>
                    </td>
                    <td className="hidden min-w-0 sm:table-cell">
                      <div className="truncate text-[11px] uppercase text-slate-400">
                        {a.platform || "instagram"}
                      </div>
                      <StatusBadge value={a.status} />
                    </td>
                    <td
                      className="hidden min-w-0 text-slate-400 md:table-cell"
                      title={
                        a.proxy_country &&
                        a.proxy_geo_country &&
                        a.proxy_country.toUpperCase() !== a.proxy_geo_country.toUpperCase()
                          ? `Не совпадает с заявленной страной (${a.proxy_country})`
                          : (a.proxy_label ?? "")
                      }
                    >
                      <div className="flex items-center gap-1 truncate">
                        <CountryFlag code={a.proxy_country} />
                        <span className="truncate">{a.proxy_label ?? "—"}</span>
                        {a.proxy_is_healthy != null ? (
                          <StatusBadge value={a.proxy_is_healthy ? "ok" : "bad"} />
                        ) : null}
                      </div>
                      {a.proxy_geo_country ? (
                        <span
                          className={
                            a.proxy_country &&
                            a.proxy_country.toUpperCase() !== a.proxy_geo_country.toUpperCase()
                              ? "inline-flex items-center gap-1 text-amber-300"
                              : "inline-flex items-center gap-1 text-slate-400"
                          }
                        >
                          <CountryFlag code={a.proxy_geo_country} />
                          {a.proxy_geo_country}
                        </span>
                      ) : null}
                      <div className="truncate text-[11px]" title={a.timezone}>
                        {a.timezone}
                      </div>
                    </td>
                    <td className="hidden min-w-0 tabular-nums text-slate-300 lg:table-cell">
                      <div>
                        {a.daily_post_cap} · {a.min_gap_hours}h
                        <span className="ml-1 text-emerald-300">{a.posts_today}</span>
                        <span className="text-slate-500">/</span>
                        <span className={a.failures_today ? "text-rose-300" : "text-slate-500"}>
                          {a.failures_today}
                        </span>
                      </div>
                      <div className="truncate text-[11px] text-slate-400" title={lastPublish}>
                        {lastPublish}
                      </div>
                      <div className="truncate text-[11px] text-orange-300" title={cooldown}>
                        {cooldown}
                      </div>
                      <label className="mt-0.5 flex items-center gap-1 text-[10px] text-slate-500">
                        <input
                          type="checkbox"
                          checked={Boolean(a.hold_for_review)}
                          onChange={async (e) => {
                            try {
                              await api.factory.updateAgentSettings(a.id, { hold_for_review: e.target.checked });
                              await reload();
                            } catch (err) {
                              push((err as Error).message, "error");
                            }
                          }}
                        />
                        проверка
                      </label>
                    </td>
                    <td className="text-right">
                      <div className="flex items-center justify-end gap-1 flex-wrap">
                        <RowIconButton
                          label={`Подключение для ${a.username}`}
                          disabled={!a.proxy_label}
                          title={
                            a.proxy_label
                              ? "Полная проверка подключения"
                              : "Сначала назначьте прокси"
                          }
                          onClick={() => setConnectionAccount(a)}
                        >
                          <Network size={14} />
                        </RowIconButton>
                        <RowIconButton
                          label={`Сессия для ${a.username}`}
                          onClick={() => setSessionAccount(a)}
                        >
                          <KeyRound size={14} />
                        </RowIconButton>
                        {a.has_totp ? (
                          <RowIconButton
                            label={`Копировать TOTP для ${a.username}`}
                            onClick={async () => {
                              try {
                                const data = await api.accounts.getTotp(a.username);
                                const ok = await copyTextToClipboard(data.totp_seed);
                                push(
                                  ok
                                    ? "Секретный ключ TOTP скопирован"
                                    : "Не удалось скопировать ключ TOTP",
                                  ok ? "success" : "error"
                                );
                              } catch (err) {
                                push((err as Error).message, "error");
                              }
                            }}
                          >
                            <Copy size={14} />
                          </RowIconButton>
                        ) : null}
                        <RowIconButton
                          label={`Сменить прокси для ${a.username}`}
                          onClick={() => setAssigningAccount(a)}
                        >
                          <Server size={14} />
                        </RowIconButton>
                        {a.status === "active" ? (
                          <RowIconButton
                            label="Пауза"
                            onClick={async () => {
                              try {
                                const updated = await api.accounts.pause(a.username);
                                setAccounts((arr) =>
                                  arr.map((x) => (x.id === updated.id ? updated : x))
                                );
                                push(`@${a.username} приостановлен`, "info");
                              } catch (err) {
                                push((err as Error).message, "error");
                              }
                            }}
                          >
                            <Pause size={14} />
                          </RowIconButton>
                        ) : a.status === "paused" || a.status === "cooldown" ? (
                          <RowIconButton
                            label="Возобновить"
                            onClick={async () => {
                              try {
                                const updated = await api.accounts.resume(a.username);
                                setAccounts((arr) =>
                                  arr.map((x) => (x.id === updated.id ? updated : x))
                                );
                                push(`@${a.username} возобновлён`, "success");
                              } catch (err) {
                                push((err as Error).message, "error");
                              }
                            }}
                          >
                            <Play size={14} />
                          </RowIconButton>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          </div>
        )}
      </Card>
      ) : null}

      <AddAccountModal
        open={openAccount}
        proxies={proxies}
        onClose={() => setOpenAccount(false)}
        onSaved={onCreatedAccount}
      />
      <AddProxyModal
        open={openProxy}
        onClose={() => setOpenProxy(false)}
        onSaved={onCreatedProxy}
      />
      <AssignProxyModal
        account={assigningAccount}
        proxies={proxies}
        open={assigningAccount !== null}
        onClose={() => setAssigningAccount(null)}
        onSaved={onAssignedProxy}
      />
      <ConnectionModal
        account={connectionAccount}
        open={connectionAccount !== null}
        onClose={() => setConnectionAccount(null)}
        onOpenProxy={() => {
          if (connectionAccount) {
            setAssigningAccount(connectionAccount);
            setConnectionAccount(null);
          }
        }}
        onOpenSessionSetup={(acc) => {
          setConnectionAccount(null);
          setSessionSetupAccount(acc);
        }}
        onResult={(account, result) => {
          if (result.proxy_label) {
            const label = result.proxy_label;
            setProxies((arr) =>
              arr.map((x) =>
                x.label === label
                  ? {
                      ...x,
                      is_healthy: result.proxy_health.ok,
                      last_known_ip: result.proxy_health.ip ?? x.last_known_ip,
                      last_geo_country:
                        result.proxy_health.geo_country ?? x.last_geo_country,
                      instagram_reachable: result.proxy_health.instagram_reachable,
                      geo_mismatch_warning: result.proxy_health.geo_mismatch,
                    }
                  : x
              )
            );
          }
          setAccounts((arr) =>
            arr.map((x) =>
              x.id === account.id
                ? {
                    ...x,
                    proxy_is_healthy: result.proxy_health.ok,
                    proxy_geo_country:
                      result.proxy_health.geo_country ?? x.proxy_geo_country,
                    proxy_last_ip: result.proxy_health.ip ?? x.proxy_last_ip,
                    session_file_exists: result.session_storage.session_file_exists,
                    session_source: result.session_storage.session_source,
                  }
                : x
            )
          );
        }}
      />
      <SessionSetupModal
        account={sessionSetupAccount}
        open={sessionSetupAccount !== null}
        onClose={() => setSessionSetupAccount(null)}
        onCompleted={onSessionSetupCompleted}
      />
      <Modal
        open={browserAccount !== null}
        onClose={() => setBrowserAccount(null)}
        title={`Браузер · @${browserAccount?.username ?? ""}`}
        widthClass="max-w-5xl"
      >
        {browserAccount ? (
          <InstagramBrowserPanel
            username={browserAccount.username}
            adminToken={adminToken}
            hasProxy={Boolean(browserAccount.proxy_label)}
            loginSurface={browserAccount.login_surface === "desktop" ? "desktop" : "mobile"}
            onSessionSaved={() => void onBrowserSessionSaved()}
          />
        ) : null}
      </Modal>
      <SessionModal
        account={sessionAccount}
        open={sessionAccount !== null}
        onClose={() => setSessionAccount(null)}
        onSaved={onImportedSession}
      />
      <EditProxyModal
        proxy={editingProxy}
        open={editingProxy !== null}
        onClose={() => setEditingProxy(null)}
        onSaved={onUpdatedProxy}
      />
    </div>
  );
}

function AddAccountModal({
  open,
  proxies,
  onClose,
  onSaved,
}: {
  open: boolean;
  proxies: ProxyOut[];
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}) {
  const { push } = useToast();
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState<AccountIn>({
    username: "",
    platform: "instagram",
    password: "",
    proxy_label: "",
    timezone: "UTC",
    daily_post_cap: 3,
    min_gap_hours: 4,
    active_hour_start: 10,
    active_hour_end: 22,
    caption_profile: "",
    totp_seed: "",
    login_identifier: "",
    email: "",
    email_password: "",
    imap_host: "",
    account_line: "",
    backup_codes: "",
    notes: "",
  });
  const [totpCopied, setTotpCopied] = useState(false);

  useEffect(() => {
    if (open && proxies.length > 0 && !form.proxy_label) {
      const first = proxies[0];
      setForm((f) => ({
        ...f,
        proxy_label: first.label,
        timezone: first.timezone?.trim() ? first.timezone : f.timezone,
      }));
    }
  }, [open, proxies, form.proxy_label]);

  function selectProxy(label: string) {
    const proxy = proxies.find((p) => p.label === label);
    setForm((f) => ({
      ...f,
      proxy_label: label,
      timezone: proxy?.timezone?.trim() ? proxy.timezone : f.timezone,
    }));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const isIgSubmit = (form.platform || "instagram") === "instagram";
    if (!form.username || !form.proxy_label || (isIgSubmit && !form.password)) {
      push("Заполните имя пользователя, пароль и прокси", "error");
      return;
    }
    setBusy(true);
    try {
      const payload: AccountIn = {
        ...form,
        caption_profile: form.caption_profile?.trim() ? form.caption_profile : null,
        totp_seed: form.totp_seed?.trim() ? form.totp_seed.trim() : null,
        login_identifier: form.login_identifier?.trim() ? form.login_identifier.trim() : null,
        email: form.email?.trim() ? form.email.trim() : null,
        email_password: form.email_password?.trim() ? form.email_password : null,
        imap_host: form.imap_host?.trim() ? form.imap_host.trim() : null,
        account_line: form.account_line?.trim() ? form.account_line.trim() : null,
        backup_codes: form.backup_codes?.trim() ? form.backup_codes.trim() : null,
        notes: form.notes?.trim() ? form.notes.trim() : null,
      };
      await api.accounts.create(payload);
      await onSaved();
      setForm({
        username: "",
        platform: "instagram",
        password: "",
        proxy_label: proxies[0]?.label ?? "",
        timezone: proxies[0]?.timezone?.trim() || "UTC",
        daily_post_cap: 3,
        min_gap_hours: 4,
        active_hour_start: 10,
        active_hour_end: 22,
        caption_profile: "",
        totp_seed: "",
        login_identifier: "",
        email: "",
        email_password: "",
        imap_host: "",
        account_line: "",
        backup_codes: "",
        notes: "",
      });
    } catch (err) {
      push((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  const isIg = (form.platform || "instagram") === "instagram";

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Добавить аккаунт"
      footer={
        <>
          <button onClick={onClose} className="btn-ghost">
            <XCircle size={16} /> Отмена
          </button>
          <button form="add-account-form" type="submit" className="btn-primary" disabled={busy}>
            <CheckCircle2 size={16} />
            {busy ? "Сохранение…" : "Сохранить аккаунт"}
          </button>
        </>
      }
    >
      <form id="add-account-form" onSubmit={submit} className="space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div>
            <label className="label">Площадка</label>
            <select
              className="input"
              value={form.platform || "instagram"}
              onChange={(e) =>
                setForm({
                  ...form,
                  platform: e.target.value as AccountIn["platform"],
                })
              }
            >
              <option value="instagram">Instagram</option>
              <option value="youtube">YouTube Shorts</option>
              <option value="tiktok">TikTok</option>
            </select>
          </div>
          <div>
            <label className="label">Имя пользователя</label>
            <input
              className="input"
              value={form.username}
              onChange={(e) => setForm({ ...form, username: e.target.value })}
              autoComplete="off"
            />
          </div>
          <div>
            <label className="label">{isIg ? "Пароль" : "Пароль (не нужен)"}</label>
            <input
              className="input"
              type="password"
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              autoComplete="new-password"
            />
            {!isIg ? (
              <p className="text-xs text-slate-500 mt-1">
                YouTube и TikTok входят через браузер и cookies.
              </p>
            ) : null}
          </div>
        </div>
        {isIg ? (
        <>
        <div>
          <label className="label">Логин Instagram (необязательно)</label>
          <input
            className="input"
            value={form.login_identifier ?? ""}
            onChange={(e) => setForm({ ...form, login_identifier: e.target.value })}
            placeholder="email, +1234567890 или username"
            autoComplete="off"
          />
          <p className="text-xs text-slate-500 mt-1">
            Если входите по email или телефону, а не по @username выше — укажите здесь.
          </p>
        </div>
        <div>
          <label className="label">Строка аккаунта (необязательно)</label>
          <textarea
            className="input min-h-[72px] font-mono text-xs"
            value={form.account_line ?? ""}
            onChange={(e) => setForm({ ...form, account_line: e.target.value })}
            placeholder="user:pass:BACKUP CODES:url"
          />
        </div>
        <div>
          <label className="label">Резервные коды 2FA (необязательно)</label>
          <textarea
            className="input min-h-[56px] font-mono text-xs"
            value={form.backup_codes ?? ""}
            onChange={(e) => setForm({ ...form, backup_codes: e.target.value })}
            placeholder="JUJW WLWP QGPU …"
          />
        </div>
        </>
        ) : null}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div>
            <label className="label">Прокси</label>
            {proxies.length === 0 ? (
              <div className="flex items-center gap-2 text-sm text-amber-300">
                <ShieldOff size={16} />
                <span>Нет прокси. Сначала добавьте.</span>
              </div>
            ) : (
              <select
                className="input"
                value={form.proxy_label}
                onChange={(e) => selectProxy(e.target.value)}
              >
                {proxies.map((p) => (
                  <option key={p.id} value={p.label}>
                    {p.label} {p.country ? `(${p.country})` : ""}
                  </option>
                ))}
              </select>
            )}
          </div>
          <div>
            <label className="label">Часовой пояс</label>
            <input
              className="input"
              value={form.timezone}
              onChange={(e) => setForm({ ...form, timezone: e.target.value })}
              placeholder="Europe/Berlin"
            />
            <p className="text-xs text-slate-500 mt-1">
              Как у прокси (подставляется при выборе)
            </p>
          </div>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div>
            <label className="label">Дневной лимит</label>
            <input
              type="number"
              className="input"
              min={1}
              max={20}
              value={form.daily_post_cap ?? 3}
              onChange={(e) => setForm({ ...form, daily_post_cap: Number(e.target.value) })}
            />
          </div>
          <div>
            <label className="label">Мин. пауза (ч)</label>
            <input
              type="number"
              step="0.5"
              className="input"
              min={0.5}
              max={24}
              value={form.min_gap_hours ?? 4}
              onChange={(e) => setForm({ ...form, min_gap_hours: Number(e.target.value) })}
            />
          </div>
          <div>
            <label className="label">Начало активности</label>
            <input
              type="number"
              className="input"
              min={0}
              max={23}
              value={form.active_hour_start ?? 10}
              onChange={(e) => setForm({ ...form, active_hour_start: Number(e.target.value) })}
            />
          </div>
          <div>
            <label className="label">Конец активности</label>
            <input
              type="number"
              className="input"
              min={1}
              max={23}
              value={form.active_hour_end ?? 22}
              onChange={(e) => setForm({ ...form, active_hour_end: Number(e.target.value) })}
            />
          </div>
        </div>
        {isIg ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div>
            <label className="label">Профиль подписей</label>
            <select
              className="input"
              value={form.caption_profile ?? ""}
              onChange={(e) => setForm({ ...form, caption_profile: e.target.value })}
            >
              <option value="">— по умолчанию —</option>
              {CAPTION_PROFILE_OPTIONS.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
            <p className="text-xs text-slate-500 mt-1">
              Настраивает пул подписей и уровни хештегов по теме.
            </p>
          </div>
          <div>
            <label className="label">Секрет TOTP (необязательно)</label>
            <input
              className="input"
              value={form.totp_seed ?? ""}
              onChange={(e) => setForm({ ...form, totp_seed: e.target.value })}
              placeholder="JBSWY3DPEHPK3PXP"
              autoComplete="off"
            />
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <button
                type="button"
                className="btn-ghost text-xs"
                disabled={!(form.totp_seed ?? "").trim()}
                title={
                  (form.totp_seed ?? "").trim()
                    ? "Скопировать Base32-секрет в буфер обмена"
                    : "Сначала введите секрет TOTP в поле выше"
                }
                onClick={async () => {
                  const seed = (form.totp_seed ?? "").trim();
                  if (!seed) return;
                  const ok = await copyTextToClipboard(seed);
                  push(
                    ok ? "Секретный ключ TOTP скопирован" : "Не удалось скопировать ключ TOTP",
                    ok ? "success" : "error"
                  );
                  if (ok) {
                    setTotpCopied(true);
                    window.setTimeout(() => setTotpCopied(false), 2000);
                  }
                }}
              >
                <Copy size={14} />{" "}
                {totpCopied ? "Скопировано" : "Копировать секретный ключ TOTP"}
              </button>
            </div>
            <p className="text-xs text-slate-500 mt-1">
              Base32-секрет для авто 2FA. Хранится локально.
            </p>
          </div>
        </div>
        ) : null}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {isIg ? (
          <>
          <div>
            <label className="label">Резервный email (необязательно)</label>
            <input
              className="input"
              type="email"
              value={form.email ?? ""}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
              autoComplete="off"
            />
          </div>
          <div>
            <label className="label">Пароль почты / пароль приложения</label>
            <input
              className="input"
              type="password"
              value={form.email_password ?? ""}
              onChange={(e) => setForm({ ...form, email_password: e.target.value })}
              autoComplete="new-password"
            />
            <p className="text-xs text-slate-500 mt-1">
              Используется для получения кода подтверждения через IMAP.
            </p>
          </div>
          <div className="md:col-span-2">
            <label className="label">IMAP хост (если домен не распознан)</label>
            <input
              className="input"
              type="text"
              value={form.imap_host ?? ""}
              onChange={(e) => setForm({ ...form, imap_host: e.target.value })}
              placeholder="imap.poczta.onet.pl"
              autoComplete="off"
            />
          </div>
          </>
          ) : null}
          <div>
            <label className="label">Заметки</label>
            <textarea
              className="input min-h-[72px]"
              value={form.notes ?? ""}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
              placeholder="Заметки администратора по аккаунту"
            />
          </div>
        </div>
      </form>
    </Modal>
  );
}

function ConnectionModal({
  account,
  open,
  onClose,
  onOpenProxy,
  onOpenSessionSetup,
  onResult,
}: {
  account: AccountOut | null;
  open: boolean;
  onClose: () => void;
  onOpenProxy: () => void;
  onOpenSessionSetup: (account: AccountOut) => void;
  onResult?: (account: AccountOut, result: AccountConnectionTestOut) => void;
}) {
  const { push } = useToast();
  const [running, setRunning] = useState(false);
  const [minting, setMinting] = useState(false);
  const [result, setResult] = useState<AccountConnectionTestOut | null>(null);
  const [lastCheckMode, setLastCheckMode] = useState<"cookies" | "mobile" | null>(null);
  const [history, setHistory] = useState<DiagnosticRunOut[]>([]);
  const [selectedHistoryId, setSelectedHistoryId] = useState<number | "current">("current");
  const [historyTick, setHistoryTick] = useState(0);

  useEffect(() => {
    if (!open) return;
    setResult(null);
    setRunning(false);
    setMinting(false);
    setLastCheckMode(null);
    setSelectedHistoryId("current");
    setHistory([]);
  }, [open, account?.username]);

  const connectionUsername = account?.username;
  useEffect(() => {
    if (!open || !connectionUsername) return;
    let cancelled = false;
    api.diagnostics
      .list({ username: connectionUsername, kind: "connection_test", limit: 5 })
      .then((rows) => {
        if (!cancelled) setHistory(rows);
      })
      .catch(() => {
        if (!cancelled) setHistory([]);
      });
    return () => {
      cancelled = true;
    };
  }, [open, connectionUsername, result?.run_id, historyTick]);

  const hasProxy = Boolean(account?.proxy_label);

  async function runTest() {
    if (!account) return;
    if (!account.proxy_label) {
      push("Сначала назначьте прокси", "error");
      return;
    }
    setRunning(true);
    setResult(null);
    setLastCheckMode("cookies");
    setSelectedHistoryId("current");
    try {
      const data = await api.accounts.testConnection(account.username, {
        probeMobile: false,
      });
      setResult(data);
      onResult?.(account, data);
      if (!data.instagram_auth.ok && isSessionMissing(data.instagram_auth)) {
        if (isInstagram(account)) {
          onOpenSessionSetup(account);
          return;
        }
      }
      push(
        data.overall_ok
          ? `@${account.username}: cookies установлены`
          : `@${account.username}: обнаружены проблемы с подключением`,
        data.overall_ok ? "success" : "error"
      );
    } catch (err) {
      push((err as Error).message, "error");
      setHistoryTick((n) => n + 1);
    } finally {
      setRunning(false);
    }
  }

  async function runMobileProbe() {
    if (!account) return;
    if (!account.proxy_label) {
      push("Сначала назначьте прокси", "error");
      return;
    }
    setRunning(true);
    setResult(null);
    setLastCheckMode("mobile");
    setSelectedHistoryId("current");
    try {
      const data = await api.accounts.testConnection(account.username, {
        probeMobile: true,
      });
      setResult(data);
      onResult?.(account, data);
      if (!data.instagram_auth.ok && isSessionMissing(data.instagram_auth)) {
        if (isInstagram(account)) {
          onOpenSessionSetup(account);
          return;
        }
      }
      push(
        data.overall_ok
          ? `@${account.username}: готов к автопостингу`
          : `@${account.username}: mobile API отклонил сессию`,
        data.overall_ok ? "success" : "error"
      );
    } catch (err) {
      push((err as Error).message, "error");
      setHistoryTick((n) => n + 1);
    } finally {
      setRunning(false);
    }
  }

  async function preparePublishSession() {
    if (!account) return;
    setMinting(true);
    setSelectedHistoryId("current");
    try {
      const minted = await api.accounts.mintMobileSession(account.username);
      if (!minted.ok) {
        push(
          minted.challenge
            ? "Нужно подтверждение Instagram (challenge) — откройте браузер или дождитесь кода"
            : minted.error ?? "Не удалось создать mobile-сессию",
          "error"
        );
        setHistoryTick((n) => n + 1);
        return;
      }
      push("Mobile-сессия создана — проверяем mobile API…", "success");
      setLastCheckMode("mobile");
      const data = await api.accounts.testConnection(account.username, {
        probeMobile: true,
      });
      setResult(data);
      onResult?.(account, data);
      push(
        data.overall_ok
          ? `@${account.username}: готов к автопостингу`
          : `@${account.username}: сессия создана, но mobile-проверка ещё не прошла`,
        data.overall_ok ? "success" : "error"
      );
    } catch (err) {
      push((err as Error).message, "error");
      setHistoryTick((n) => n + 1);
    } finally {
      setMinting(false);
    }
  }

  const latestFinished = history.find((h) => h.status !== "running") ?? null;
  const selectedHistory =
    selectedHistoryId === "current"
      ? null
      : history.find((h) => h.id === selectedHistoryId) ?? null;
  const viewingHistory = selectedHistory != null && !running;

  const displayLogs =
    selectedHistoryId === "current"
      ? result?.logs ?? (running ? [] : latestFinished?.logs ?? [])
      : selectedHistory?.logs ?? [];

  const historyOverall: StepVisual | null = viewingHistory
    ? selectedHistory.status === "ok"
      ? "ok"
      : selectedHistory.status === "warn"
        ? "warn"
        : selectedHistory.status === "fail"
          ? "fail"
          : "running"
    : null;

  const step1: StepVisual = running
    ? "running"
    : result
      ? result.proxy_assigned
        ? "ok"
        : "fail"
      : viewingHistory && historyOverall
        ? historyOverall === "running"
          ? "pending"
          : account?.proxy_label
            ? "ok"
            : "fail"
        : account?.proxy_label
          ? "ok"
          : "pending";

  const step2: StepVisual = running
    ? "running"
    : result
      ? result.proxy_health.ok
        ? result.proxy_health.geo_mismatch
          ? "warn"
          : "ok"
        : "fail"
      : viewingHistory && historyOverall && historyOverall !== "running"
        ? historyOverall === "ok"
          ? "ok"
          : "fail"
        : "pending";

  const storagePresent = (storage: AccountConnectionTestOut["session_storage"]) =>
    storage.session_source !== "none" ||
    storage.has_session_id ||
    storage.session_file_exists;

  const step3: StepVisual = running
    ? "running"
    : result
      ? storagePresent(result.session_storage)
        ? "ok"
        : "fail"
      : viewingHistory && historyOverall && historyOverall !== "running"
        ? historyOverall === "ok"
          ? "ok"
          : "fail"
        : account?.session_source && account.session_source !== "none"
          ? "ok"
          : "pending";

  const step4: StepVisual = running
    ? "running"
    : result
      ? result.instagram_auth.ok
        ? "ok"
        : result.instagram_auth.challenge
          ? "warn"
          : "fail"
      : viewingHistory && historyOverall
        ? historyOverall
        : "pending";

  const missingSession =
    result?.instagram_auth != null && isSessionMissing(result.instagram_auth);

  const sessionExpired =
    lastCheckMode === "mobile" &&
    result?.instagram_auth != null &&
    !result.instagram_auth.ok &&
    isSessionExpired(result.instagram_auth);

  const cookiesOnlyOk =
    lastCheckMode === "cookies" && result != null && result.overall_ok;
  const mobileOk =
    lastCheckMode === "mobile" && result != null && result.overall_ok;

  const statusBanner =
    result != null && selectedHistoryId === "current"
      ? {
          ok: result.overall_ok,
          title: result.overall_ok
            ? cookiesOnlyOk
              ? isInstagram(account)
                ? "Cookies установлены"
                : "Cookies Studio на диске"
              : mobileOk
                ? "Готов к автопостингу"
                : "Подключение в порядке"
            : isInstagram(account)
              ? "Не готов к автопостингу"
              : "Проверка не пройдена",
          detail: !result.overall_ok
            ? result.instagram_auth.error
            : cookiesOnlyOk
              ? isInstagram(account)
                ? "Мобильный API не проверялся — для автопостинга нажмите «Проверить мобильный API»"
                : "Живость сессии на сервере не проверялась"
              : null,
          checkedAt: result.checked_at,
        }
      : viewingHistory
        ? {
            ok: selectedHistory.status === "ok",
            title:
              selectedHistory.status === "ok"
                ? "Проверка пройдена (из истории)"
                : selectedHistory.status === "running"
                  ? "Проверка в истории ещё помечена как running"
                  : "Проверка не пройдена (из истории)",
            detail: selectedHistory.summary,
            checkedAt: selectedHistory.finished_at ?? selectedHistory.created_at,
          }
        : null;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Подключение · @${account?.username ?? ""}`}
      footer={
        <>
          <button type="button" onClick={onClose} className="btn-ghost">
            <XCircle size={16} /> Закрыть
          </button>
          {isInstagram(account) ? (
          <button
            type="button"
            className="btn-ghost"
            disabled={running || minting || !account || !hasProxy}
            onClick={() => void runMobileProbe()}
            title={
              hasProxy
                ? "Может инвалидировать web-cookie из Dolphin"
                : "Сначала назначьте прокси"
            }
          >
            <ShieldOff size={16} className={running && lastCheckMode === "mobile" ? "animate-pulse" : ""} />
            {running && lastCheckMode === "mobile" ? "Мобильный…" : "Проверить мобильный API"}
          </button>
          ) : null}
          <button
            type="button"
            className="btn-primary"
            disabled={running || minting || !account || !hasProxy}
            title={hasProxy ? undefined : "Сначала назначьте прокси"}
            onClick={runTest}
          >
            <RefreshCw size={16} className={running && lastCheckMode === "cookies" ? "animate-spin" : ""} />
            {running && lastCheckMode === "cookies" ? "Проверка…" : "Запустить проверку"}
          </button>
        </>
      }
    >
      <div className="space-y-4">
        {!hasProxy ? (
          <p className="rounded-xl border border-amber-800/50 bg-amber-950/20 px-3 py-2 text-sm text-amber-200">
            Сначала назначьте прокси
          </p>
        ) : null}
        <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-3 text-sm space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-slate-400">Прокси:</span>
            <CountryFlag code={account?.proxy_country} />
            <span className="font-mono text-xs">{account?.proxy_label ?? "—"}</span>
            {account?.proxy_last_ip ? (
              <span className="text-xs text-slate-500">· {account.proxy_last_ip}</span>
            ) : null}
          </div>
          <div className="flex flex-wrap gap-2 text-[10px] uppercase tracking-wide">
            {isInstagram(account) && account?.has_session_id ? (
              <span className="text-brand-300">sessionid в БД</span>
            ) : null}
            {account?.session_file_exists ? (
              <span className="text-sky-300">Файл cookies</span>
            ) : null}
            {account ? (
              <span className="text-slate-500">{sessionSourceLabel(account.session_source)}</span>
            ) : null}
          </div>
          <p className="text-xs text-slate-500">
            {isInstagram(account)
              ? "«Запустить проверку» смотрит прокси и наличие cookies (без мобильного API). «Проверить мобильный API» нужно только для автопостинга Instagram и может сжечь web-cookie."
              : "«Запустить проверку» смотрит прокси и наличие Playwright cookies Studio на диске. Живость сессии на сервере не проверяется."}
          </p>
        </div>

        <div className="space-y-2">
          <ConnectionStepRow
            label="1. Прокси назначен"
            state={step1}
            detail={
              result
                ? result.proxy_label ?? "Нет прокси"
                : account?.proxy_label ?? "Не назначен"
            }
          />
          <ConnectionStepRow
            label="2. Прокси health"
            state={step2}
            detail={
              result?.proxy_health.ok ? (
                <span className="inline-flex items-center gap-2 flex-wrap">
                  IP: {result.proxy_health.ip ?? "—"}
                  <CountryFlag code={result.proxy_health.geo_country} showCode />
                  {isInstagram(account) ? (
                    result.proxy_health.instagram_reachable
                      ? "· Instagram доступен"
                      : "· Instagram недоступен"
                  ) : (
                    "· IP прокси"
                  )}
                  {result.proxy_health.geo_mismatch ? (
                    <span className="text-amber-300">Гео не совпадает с заявленной страной</span>
                  ) : null}
                </span>
              ) : (
                result?.proxy_health.error ??
                (running
                  ? "Проверка прокси…"
                  : viewingHistory
                    ? selectedHistory.summary ?? "См. лог истории"
                    : "Ещё не проверено")
              )
            }
          />
          <ConnectionStepRow
            label="3. Хранилище сессии"
            state={step3}
            detail={
              result ? (
                <span className="inline-flex items-center gap-2 flex-wrap">
                  {sessionSourceLabel(result.session_storage.session_source)}
                  {isInstagram(account) && result.session_storage.has_session_id ? (
                    <span className="text-brand-300">sessionid</span>
                  ) : null}
                  {result.session_storage.session_file_exists ? (
                    <span className="text-sky-300">файл</span>
                  ) : null}
                  {result.session_storage.device_file_exists ? (
                    <span className="text-slate-500">device</span>
                  ) : null}
                </span>
              ) : running ? (
                "Проверка хранилища…"
              ) : viewingHistory ? (
                selectedHistory.summary ?? "См. лог истории"
              ) : account ? (
                sessionSourceLabel(account.session_source)
              ) : (
                "Ещё не проверено"
              )
            }
          />
          <ConnectionStepRow
            label={
              isInstagram(account)
                ? result?.instagram_auth.ok
                  ? lastCheckMode === "cookies"
                    ? "4. Вход Instagram (cookies)"
                    : "4. Вход Instagram — ок"
                  : result
                    ? lastCheckMode === "mobile"
                      ? "4. Вход Instagram недействителен"
                      : "4. Вход Instagram"
                    : "4. Вход Instagram"
                : result?.instagram_auth.ok
                  ? "4. Cookies Studio на диске"
                  : result
                    ? "4. Cookies Studio"
                    : "4. Cookies Studio"
            }
            state={step4}
            detail={
              result?.instagram_auth.ok ? (
                <span>
                  {lastCheckMode === "cookies"
                    ? `Cookie в хранилище (${result.instagram_auth.method})`
                    : `Аутентификация через ${result.instagram_auth.method}`}
                  {result.instagram_auth.ig_username
                    ? ` · @${result.instagram_auth.ig_username}`
                    : ""}
                </span>
              ) : (
                result?.instagram_auth.error ??
                (running
                  ? lastCheckMode === "mobile"
                    ? "Проверка сессии… (до 1–2 мин)"
                    : "Проверка auth…"
                  : viewingHistory
                    ? selectedHistory.summary ?? "См. лог истории"
                    : "Ещё не проверено")
              )
            }
          />
        </div>

        {statusBanner ? (
          <div
            className={`rounded-xl border p-3 text-sm ${
              statusBanner.ok
                ? "border-emerald-800/60 bg-emerald-950/30 text-emerald-200"
                : "border-rose-800/60 bg-rose-950/30 text-rose-200"
            }`}
          >
            <div className="font-medium">{statusBanner.title}</div>
            {statusBanner.detail ? (
              <div className="mt-1 text-xs opacity-90">{statusBanner.detail}</div>
            ) : null}
            {statusBanner.checkedAt ? (
              <div className="mt-1 text-xs opacity-70">
                Проверено {new Date(statusBanner.checkedAt).toLocaleString()}
              </div>
            ) : null}
          </div>
        ) : null}

        {missingSession ? (
          <div className="rounded-xl border border-amber-500/50 bg-amber-950/40 p-4 text-sm text-amber-100">
            <div className="font-semibold text-amber-200">
              {isInstagram(account)
                ? "Сессия не найдена — импортируйте sessionid"
                : "Нет Playwright cookies — импортируйте файл или сохраните сессию в браузере"}
            </div>
            <p className="mt-1 text-xs text-amber-100/90">
              {isInstagram(account)
                ? "Для автопостинга нужна cookie sessionid из Dolphin или браузера. Нажмите кнопку ниже, чтобы вставить сессию."
                : "YouTube и TikTok публикуют через Studio. Импортируйте cookies или откройте браузер и нажмите «Сохранить»."}
            </p>
          </div>
        ) : null}

        {isInstagram(account) && sessionExpired && !missingSession ? (
          <div className="rounded-xl border border-amber-500/50 bg-amber-950/40 p-4 text-sm text-amber-100">
            <div className="font-semibold text-amber-200">
              Автопостинг: пароль или mobile-сессия
            </div>
            <p className="mt-1 text-xs text-amber-100/90">{SESSION_EXPIRED_MOBILE_HINT}</p>
          </div>
        ) : null}

        <div className="space-y-2">
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <div className="text-xs font-medium text-slate-400 uppercase tracking-wide">
              Диагностический лог
            </div>
            {history.length > 0 ? (
              <select
                className="input py-1 text-xs max-w-[220px]"
                value={selectedHistoryId === "current" ? "current" : String(selectedHistoryId)}
                onChange={(e) => {
                  const v = e.target.value;
                  setSelectedHistoryId(v === "current" ? "current" : Number(v));
                }}
              >
                <option value="current">Последняя проверка</option>
                {history.map((h) => (
                  <option key={h.id} value={h.id}>
                    {new Date(h.created_at).toLocaleString()} — {h.status}
                  </option>
                ))}
              </select>
            ) : null}
          </div>
          <DiagnosticLogPanel
            lines={displayLogs}
            emptyLabel={
              running
                ? lastCheckMode === "mobile"
                  ? "Выполняется mobile-проверка… (может занять 1–2 минуты)"
                  : "Выполняется проверка cookies и прокси…"
                : "Запустите проверку, чтобы увидеть пошаговые логи."
            }
            maxHeightClass="max-h-64"
          />
        </div>

        <div className="flex flex-wrap gap-2">
          <button type="button" className="btn-ghost text-xs" onClick={onOpenProxy}>
            <Server size={14} /> Сменить прокси
          </button>
          {isInstagram(account) ? (
          <button
            type="button"
            className={
              missingSession
                ? "btn-primary text-sm shadow-lg shadow-brand-500/20 ring-2 ring-brand-400/60"
                : "btn-ghost text-xs"
            }
            onClick={() => account && onOpenSessionSetup(account)}
          >
            <KeyRound size={14} /> Настроить сессию
          </button>
          ) : null}
          {isInstagram(account) && sessionExpired && !missingSession ? (
            <button
              type="button"
              className="btn-primary text-sm shadow-lg shadow-brand-500/20"
              disabled={minting || running || !account}
              onClick={() => void preparePublishSession()}
            >
              <Sparkles size={14} className={minting ? "animate-spin" : ""} />
              {minting ? "Создание mobile-сессии…" : "Подготовить к автопостингу"}
            </button>
          ) : null}
        </div>
      </div>
    </Modal>
  );
}

function SessionModal({
  account,
  open,
  onClose,
  onSaved,
}: {
  account: AccountOut | null;
  open: boolean;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}) {
  const { push } = useToast();
  const [tab, setTab] = useState<"import" | "export">("import");
  const [busy, setBusy] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [verifyResult, setVerifyResult] = useState<AccountConnectionTestOut | null>(null);
  const [sessionId, setSessionId] = useState("");
  const [exportData, setExportData] = useState<AccountSessionOut | null>(null);
  const [exportLoading, setExportLoading] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [fingerprintFile, setFingerprintFile] = useState<File | null>(null);
  const [fileImportBusy, setFileImportBusy] = useState(false);
  const [fpImportBusy, setFpImportBusy] = useState(false);
  const [downloadBusy, setDownloadBusy] = useState<
    "cookies" | "playwright" | "fingerprint" | null
  >(null);
  const ig = isInstagram(account);

  useEffect(() => {
    if (!open) return;
    setTab("import");
    setSessionId("");
    setExportData(null);
    setExportError(null);
    setVerifyResult(null);
    setImportFile(null);
    setFingerprintFile(null);
    setDownloadBusy(null);
  }, [open, account?.username]);

  useEffect(() => {
    if (!open || !account || tab !== "export") return;
    if (!isInstagram(account)) {
      setExportLoading(false);
      setExportData(null);
      setExportError(null);
      return;
    }
    let cancelled = false;
    setExportLoading(true);
    setExportError(null);
    setExportData(null);
    api.accounts
      .getSession(account.username)
      .then((data) => {
        if (!cancelled) setExportData(data);
      })
      .catch((err) => {
        if (!cancelled) setExportError((err as Error).message);
      })
      .finally(() => {
        if (!cancelled) setExportLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, account, tab]);

  async function submitImport(e: React.FormEvent) {
    e.preventDefault();
    if (!account) return;
    // Prefer file import when a cookies file is selected (footer Save shared path).
    if (importFile) {
      await submitFileImport();
      return;
    }
    if (!ig) {
      push(
        "Выберите JSON cookies YouTube/TikTok или файл состояния Playwright",
        "error"
      );
      return;
    }
    // Decode %3A → : (Dolphin / browser often export URL-encoded sessionid).
    const trimmed = decodeURIComponent(sessionId.trim().replace(/\+/g, " "));
    if (trimmed.length < 31) {
      push(
        ig
          ? "Вставьте sessionid (31+ символов) или выберите JSON/TXT cookies из Dolphin"
          : "Выберите JSON cookies YouTube/TikTok или файл состояния Playwright",
        "error"
      );
      return;
    }
    setBusy(true);
    try {
      const payload: AccountSessionUpdate = { session_id: trimmed };
      await api.accounts.updateSession(account.username, payload);
      setSessionId(trimmed);
      setVerifyResult(null);
      await onSaved();
      // Do not auto-call testConnection — mobile probe often burns the web sessionid.
    } catch (err) {
      push((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  async function copyExport() {
    if (!exportData?.session_id) return;
    const ok = await copyTextToClipboard(exportData.session_id);
    push(ok ? "Сессия скопирована" : "Не удалось скопировать", ok ? "success" : "error");
  }

  async function verifySession() {
    if (!account) return;
    setVerifying(true);
    setVerifyResult(null);
    try {
      const data = await api.accounts.testConnection(account.username, {
        probeMobile: isInstagram(account),
      });
      setVerifyResult(data);
      push(
        data.instagram_auth.ok ? "Сессия действительна" : "Проверка сессии не пройдена",
        data.instagram_auth.ok ? "success" : "error"
      );
    } catch (err) {
      push((err as Error).message, "error");
    } finally {
      setVerifying(false);
    }
  }

  async function submitFileImport() {
    if (!account || !importFile) return;
    setFileImportBusy(true);
    try {
      const result = await api.accounts.importCookiesFile(account.username, importFile);
      setSessionId(result.session_id);
      push(
        `Cookies импортированы (${result.format === "dolphin" ? "Dolphin" : "Playwright"})`,
        "success"
      );
      setImportFile(null);
      setVerifyResult(null);
      await onSaved();
      // Do not auto-call testConnection — mobile probe often burns the web sessionid.
    } catch (err) {
      push((err as Error).message, "error");
    } finally {
      setFileImportBusy(false);
    }
  }

  async function submitFingerprintImport() {
    if (!account || !fingerprintFile) return;
    setFpImportBusy(true);
    try {
      await api.accounts.importDeviceFingerprint(account.username, fingerprintFile);
      push("Отпечаток устройства сохранён", "success");
      setFingerprintFile(null);
      await onSaved();
    } catch (err) {
      push((err as Error).message, "error");
    } finally {
      setFpImportBusy(false);
    }
  }

  async function downloadExport(
    kind: "cookies" | "playwright" | "fingerprint",
    fn: (username: string) => Promise<void>
  ) {
    if (!account) return;
    setDownloadBusy(kind);
    try {
      await fn(account.username);
      push("Файл скачан", "success");
    } catch (err) {
      const msg = (err as Error).message;
      if (msg.includes("404") || msg.toLowerCase().includes("не найден")) {
        push(
          kind === "playwright"
            ? ig
              ? "Файл состояния Playwright ещё не создан — сначала выполните автовход"
              : "Файл состояния Playwright не найден — импортируйте cookies или сохраните сессию в браузере"
            : kind === "fingerprint"
              ? "Отпечаток устройства не найден для этого аккаунта"
              : "Сессия не найдена — импортируйте cookies или войдите в аккаунт",
          "error"
        );
      } else {
        push(msg, "error");
      }
    } finally {
      setDownloadBusy(null);
    }
  }

  const title = `Сессия · @${account?.username ?? ""}`;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      footer={
        tab === "import" ? (
          <>
            <button type="button" onClick={onClose} className="btn-ghost">
              <XCircle size={16} /> Отмена
            </button>
            <button
              form="import-session-form"
              type="submit"
              className="btn-primary"
              disabled={busy || fileImportBusy}
            >
              <CheckCircle2 size={16} />
              {busy || fileImportBusy
                ? importFile
                  ? "Импорт…"
                  : "Сохранение…"
                : importFile
                  ? "Импортировать файл"
                  : "Сохранить сессию"}
            </button>
          </>
        ) : (
          <button type="button" onClick={onClose} className="btn-ghost">
            <XCircle size={16} /> Закрыть
          </button>
        )
      }
    >
      <div className="flex gap-1 mb-4 p-1 rounded-lg bg-slate-900/60 border border-slate-800">
        <button
          type="button"
          className={`flex-1 text-sm py-1.5 rounded-md ${
            tab === "import" ? "bg-slate-800 text-white" : "text-slate-400 hover:text-slate-200"
          }`}
          onClick={() => setTab("import")}
        >
          Импорт
        </button>
        <button
          type="button"
          className={`flex-1 text-sm py-1.5 rounded-md ${
            tab === "export" ? "bg-slate-800 text-white" : "text-slate-400 hover:text-slate-200"
          }`}
          onClick={() => setTab("export")}
        >
          Экспорт
        </button>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-3 text-sm mb-4 space-y-2">
        <div className="text-slate-400">Хранение сессии (на аккаунт)</div>
        <div className="flex flex-wrap gap-2 text-xs">
          {ig ? (
          <span className={account?.has_session_id ? "text-brand-300" : "text-slate-500"}>
            sessionid в БД: {account?.has_session_id ? "да" : "нет"}
          </span>
          ) : null}
          <span className={account?.session_file_exists ? "text-sky-300" : "text-slate-500"}>
            Файл cookies: {account?.session_file_exists ? "да" : "нет"}
          </span>
          <span className="text-slate-400">
            Источник: {account ? sessionSourceLabel(account.session_source) : "—"}
          </span>
        </div>
        {account?.session_file_updated_at ? (
          <div className="text-xs text-slate-500">
            Cookies обновлены {new Date(account.session_file_updated_at).toLocaleString()}
          </div>
        ) : null}
        <button
          type="button"
          className="btn-ghost text-xs mt-1"
          disabled={verifying || !account}
          onClick={verifySession}
        >
          <RefreshCw size={14} className={verifying ? "animate-spin" : ""} />
          {verifying ? "Проверка…" : "Проверить сессию"}
        </button>
        {ig ? (
        <p className="text-xs text-amber-200/90">
          Mobile-проверка может инвалидировать web-cookie. Не запускайте сразу после
          импорта, если нужен экспорт в Dolphin.
        </p>
        ) : (
        <p className="text-xs text-slate-500">
          Проверка смотрит прокси и наличие Playwright cookies Studio на диске.
        </p>
        )}
        {verifyResult ? (
          <div
            className={`text-xs rounded-lg p-2 space-y-1 ${
              verifyResult.instagram_auth.ok
                ? "text-emerald-300 bg-emerald-950/40"
                : "text-rose-300 bg-rose-950/40"
            }`}
          >
            <div>
              {verifyResult.instagram_auth.ok
                ? `Действительна через ${verifyResult.instagram_auth.method}${
                    verifyResult.instagram_auth.ig_username
                      ? ` (@${verifyResult.instagram_auth.ig_username})`
                      : ""
                  }`
                : verifyResult.instagram_auth.error ?? "Сессия недействительна"}
            </div>
            {!verifyResult.instagram_auth.ok &&
            isSessionExpired(verifyResult.instagram_auth) ? (
              <p className="text-amber-100/90">{SESSION_EXPIRED_MOBILE_HINT}</p>
            ) : null}
          </div>
        ) : null}
      </div>

      {tab === "import" ? (
        <div className="space-y-4">
          <form id="import-session-form" onSubmit={submitImport} className="space-y-4">
            <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-3 text-sm">
              <div className="text-slate-400">
                {ig ? "Аккаунт Instagram" : `Аккаунт ${account?.platform === "youtube" ? "YouTube" : "TikTok"}`}
              </div>
              <div className="font-medium">@{account?.username ?? "—"}</div>
              <div className="mt-2 text-slate-400">Текущий статус</div>
              <div className="text-xs">
                {ig && account?.has_session_id ? (
                  <span className="text-brand-300">Cookie сессии сохранена — вставьте новую для замены</span>
                ) : account?.session_file_exists ? (
                  <span className="text-sky-300">Playwright cookies на диске — импортируйте файл для замены</span>
                ) : (
                  <span className="text-slate-500">Сессия ещё не импортирована</span>
                )}
              </div>
            </div>
            {ig ? (
            <div>
              <label className="label" htmlFor="import-session-id">
                cookie sessionid
              </label>
              <textarea
                id="import-session-id"
                className="input min-h-[88px] font-mono text-xs"
                value={sessionId}
                onChange={(e) => setSessionId(e.target.value)}
                placeholder="Вставьте sessionid из Dolphin / devtools браузера"
                autoComplete="off"
                spellCheck={false}
              />
              <p className="text-xs text-slate-500 mt-1">
                Импортируйте после подтверждения challenge в Dolphin на том же прокси.
                Если в значении есть <span className="font-mono">%3A</span>, оно будет
                декодировано в <span className="font-mono">:</span> автоматически.
                После импорта файла sessionid появится здесь. Не жмите «Проверить» сразу —
                mobile API часто отклоняет web-cookie из Dolphin.
              </p>
            </div>
            ) : null}
          </form>
          <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-3 space-y-3">
            <div className="text-sm text-slate-400">Импорт из файла</div>
            <p className="text-xs text-slate-500">
              JSON cookies Dolphin (.json / .txt) или файл состояния Playwright.
              {ig
                ? " Лишние cookies (Google, реклама) отфильтруются — нужен sessionid Instagram."
                : " Останутся cookies YouTube/Google или TikTok."}{" "}
              После выбора файла нажмите «Импортировать файл» внизу.
            </p>
            <input
              type="file"
              accept=".json,.txt,application/json,text/plain"
              aria-label="Импорт cookies из файла"
              className="block w-full text-xs text-slate-400 file:mr-3 file:py-1.5 file:px-3 file:rounded-md file:border-0 file:text-xs file:bg-slate-800 file:text-slate-200"
              onChange={(e) => setImportFile(e.target.files?.[0] ?? null)}
            />
            {importFile ? (
              <p className="text-xs text-brand-300">Выбран: {importFile.name}</p>
            ) : null}
          </div>
          {ig ? (
          <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-3 space-y-3">
            <div className="text-sm text-slate-400">Импорт отпечатка устройства</div>
            <p className="text-xs text-slate-500">
              JSON с диска (`device_имя.json`). Импортируйте только тот же отпечаток, с которым
              жила сессия — чужой отпечаток на живой сессии повышает риск детекта.
            </p>
            <input
              type="file"
              accept=".json,.txt,application/json,text/plain"
              aria-label="Импорт отпечатка из файла"
              className="block w-full text-xs text-slate-400 file:mr-3 file:py-1.5 file:px-3 file:rounded-md file:border-0 file:text-xs file:bg-slate-800 file:text-slate-200"
              onChange={(e) => setFingerprintFile(e.target.files?.[0] ?? null)}
            />
            {fingerprintFile ? (
              <p className="text-xs text-brand-300">Выбран: {fingerprintFile.name}</p>
            ) : null}
            <button
              type="button"
              className="btn-ghost text-sm"
              disabled={!fingerprintFile || fpImportBusy || !account}
              onClick={() => void submitFingerprintImport()}
            >
              {fpImportBusy ? "Импорт…" : "Импортировать отпечаток"}
            </button>
          </div>
          ) : null}
        </div>
      ) : (
        <div className="space-y-4">
          <p className="text-xs text-amber-300/90">
            Конфиденциальные данные — копируйте только в доверенные инструменты (Dolphin, бэкап).
          </p>
          {ig && exportLoading ? (
            <div className="text-sm text-slate-400">Загрузка сессии…</div>
          ) : ig && exportError ? (
            <div className="text-sm text-slate-400 rounded-xl border border-slate-800 p-3">
              {exportError.includes("404") ||
              /not found|не найден/i.test(exportError)
                ? "Сессия не найдена — импортируйте sessionid или сначала войдите в аккаунт."
                : exportError}
            </div>
          ) : ig && exportData ? (
            <>
              <div className="text-xs text-slate-500">
                Источник:{" "}
                <span className="text-slate-300">
                  {exportData.source === "database" ? "база данных" : "сохранённый файл сессии"}
                </span>
                {exportData.session_file_exists ? " · файл сессии на диске" : null}
              </div>
              <textarea
                readOnly
                className="input min-h-[88px] font-mono text-xs"
                value={exportData.session_id}
              />
              <button type="button" className="btn-primary text-sm" onClick={copyExport}>
                <Copy size={14} /> Копировать sessionid
              </button>
            </>
          ) : null}
          <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-3 space-y-2">
            <div className="text-sm text-slate-300">Для Dolphin / миграции</div>
            <p className="text-xs text-slate-500">
              {ig
                ? "Скачайте cookies, файл состояния Playwright или отпечаток устройства."
                : "Скачайте cookies площадки или файл состояния Playwright (сессия Studio)."}
            </p>
            <div className="flex flex-col gap-2">
              <button
                type="button"
                className="btn-ghost text-sm justify-start"
                disabled={!!downloadBusy || !account}
                onClick={() => downloadExport("cookies", api.accounts.exportCookies)}
              >
                <Download size={14} className={downloadBusy === "cookies" ? "animate-pulse" : ""} />
                {downloadBusy === "cookies" ? "Скачивание…" : "Скачать cookies (Dolphin)"}
              </button>
              <button
                type="button"
                className="btn-ghost text-sm justify-start"
                disabled={!!downloadBusy || !account}
                onClick={() =>
                  downloadExport("playwright", api.accounts.exportPlaywrightState)
                }
              >
                <Download
                  size={14}
                  className={downloadBusy === "playwright" ? "animate-pulse" : ""}
                />
                {downloadBusy === "playwright"
                  ? "Скачивание…"
                  : "Скачать файл состояния Playwright"}
              </button>
              {ig ? (
              <button
                type="button"
                className="btn-ghost text-sm justify-start"
                disabled={!!downloadBusy || !account}
                onClick={() =>
                  downloadExport("fingerprint", api.accounts.exportDeviceFingerprint)
                }
              >
                <Download
                  size={14}
                  className={downloadBusy === "fingerprint" ? "animate-pulse" : ""}
                />
                {downloadBusy === "fingerprint"
                  ? "Скачивание…"
                  : "Скачать отпечаток устройства"}
              </button>
              ) : null}
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
}

function AssignProxyModal({
  account,
  proxies,
  open,
  onClose,
  onSaved,
}: {
  account: AccountOut | null;
  proxies: ProxyOut[];
  open: boolean;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}) {
  const { push } = useToast();
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(false);
  const [proxyLabel, setProxyLabel] = useState("");
  const [testResult, setTestResult] = useState<ProxyOut | null>(null);

  useEffect(() => {
    if (!open || !account) return;
    const currentExists = proxies.some((p) => p.label === account.proxy_label);
    setProxyLabel(currentExists ? account.proxy_label ?? "" : proxies[0]?.label ?? "");
    setTestResult(null);
  }, [account, open, proxies]);

  const selectedProxy = proxies.find((p) => p.label === proxyLabel) ?? null;

  async function runProxyTest() {
    if (!proxyLabel) {
      push("Выберите прокси", "error");
      return;
    }
    setTesting(true);
    try {
      const updated = await api.proxies.check(proxyLabel);
      setTestResult(updated);
      if (!updated.is_healthy) {
        push(updated.check_detail?.trim() || "Прокси недоступен", "error");
      } else if (updated.check_detail?.trim()) {
        push(updated.check_detail.trim(), "info");
      }
    } catch (err) {
      push(formatApiError(err), "error");
    } finally {
      setTesting(false);
    }
  }

  async function testAndSave() {
    if (!account || !proxyLabel) return;
    setTesting(true);
    setBusy(true);
    try {
      const updated = await api.proxies.check(proxyLabel);
      setTestResult(updated);
      if (!updated.is_healthy) {
        push(
          `${updated.check_detail?.trim() || "Прокси недоступен"} — не сохранён`,
          "error"
        );
        return;
      }
      if (updated.instagram_reachable === false) {
        push(
          `${updated.check_detail?.trim() || "Instagram недоступен через прокси"} — не сохранён`,
          "error"
        );
        return;
      }
      const payload: AccountProxyUpdate = { proxy_label: proxyLabel };
      await api.accounts.updateProxy(account.username, payload);
      await onSaved();
      push("Прокси проверен и сохранён", "success");
    } catch (err) {
      push((err as Error).message, "error");
    } finally {
      setTesting(false);
      setBusy(false);
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!account) return;
    if (proxies.length === 0) {
      push("Сначала добавьте прокси", "error");
      return;
    }
    if (!proxyLabel) {
      push("Выберите прокси", "error");
      return;
    }
    setBusy(true);
    try {
      const payload: AccountProxyUpdate = { proxy_label: proxyLabel };
      await api.accounts.updateProxy(account.username, payload);
      await onSaved();
    } catch (err) {
      push((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Сменить прокси · @${account?.username ?? ""}`}
      footer={
        <>
          <button type="button" onClick={onClose} className="btn-ghost">
            <XCircle size={16} /> Отмена
          </button>
          <button
            type="button"
            className="btn-ghost"
            disabled={busy || testing || proxies.length === 0 || !proxyLabel}
            onClick={testAndSave}
          >
            <RefreshCw size={16} className={testing ? "animate-spin" : ""} />
            Проверить и сохранить
          </button>
          <button
            form="assign-proxy-form"
            type="submit"
            className="btn-primary"
            disabled={busy || proxies.length === 0}
          >
            <CheckCircle2 size={16} />
            {busy ? "Сохранение…" : "Сохранить прокси"}
          </button>
        </>
      }
    >
      <form id="assign-proxy-form" onSubmit={submit} className="space-y-4">
        <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-3 text-sm">
          <div className="text-slate-400">Аккаунт Instagram</div>
          <div className="font-medium">@{account?.username ?? "—"}</div>
          <div className="mt-2 text-slate-400">Текущий прокси</div>
          <div className="font-mono text-xs">{account?.proxy_label ?? "—"}</div>
        </div>
        <div>
          <label className="label">Прокси</label>
          {proxies.length === 0 ? (
            <div className="flex items-center gap-2 text-sm text-amber-300">
              <ShieldOff size={16} />
              <span>Нет прокси. Сначала добавьте.</span>
            </div>
          ) : (
            <div className="space-y-2">
              <div className="flex gap-2">
                <select
                  className="input flex-1"
                  value={proxyLabel}
                  onChange={(e) => {
                    setProxyLabel(e.target.value);
                    setTestResult(null);
                  }}
                >
                  {proxies.map((p) => (
                    <option key={p.id} value={p.label}>
                      {proxyOptionLabel(p)}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className="btn-ghost shrink-0"
                  disabled={testing || !proxyLabel}
                  aria-label="Проверить выбранный прокси"
                  onClick={runProxyTest}
                >
                  <RefreshCw size={14} className={testing ? "animate-spin" : ""} />
                  {testing ? "Проверка…" : "Проверить прокси"}
                </button>
              </div>
              {selectedProxy ? (
                <div className="flex items-center gap-2 text-xs text-slate-400">
                  <CountryFlag code={selectedProxy.country} showCode />
                </div>
              ) : null}
              {testResult ? (
                <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-3 text-xs space-y-1">
                  <div className="flex items-center gap-2">
                    <StatusBadge value={testResult.is_healthy ? "ok" : "bad"} />
                    <span className="text-slate-300">
                      {testResult.is_healthy ? "Работает" : "Недоступен"}
                    </span>
                  </div>
                  <div className="text-slate-400">
                    IP: <span className="text-slate-200">{testResult.last_known_ip ?? "—"}</span>
                  </div>
                  <div className="text-slate-400 flex items-center gap-1.5">
                    Гео:
                    <CountryFlag code={testResult.last_geo_country} showCode />
                    {testResult.geo_mismatch_warning ? (
                      <span className="text-amber-300">Не совпадает</span>
                    ) : null}
                  </div>
                  <div className="text-slate-400">
                    Instagram:{" "}
                    <span
                      className={
                        testResult.instagram_reachable === false
                          ? "text-rose-300"
                          : testResult.instagram_reachable
                            ? "text-emerald-300"
                            : "text-slate-500"
                      }
                    >
                      {testResult.instagram_reachable === false
                        ? "недоступен"
                        : testResult.instagram_reachable
                          ? "доступен"
                          : "—"}
                    </span>
                  </div>
                  {testResult.last_checked_at ? (
                    <div className="text-slate-500">
                      Проверено {new Date(testResult.last_checked_at).toLocaleString()}
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          )}
          <p className="text-xs text-slate-500 mt-1">
            Все действия Instagram для этого аккаунта будут выполняться через выбранный прокси.
          </p>
        </div>
      </form>
    </Modal>
  );
}

function EditProxyModal({
  proxy,
  open,
  onClose,
  onSaved,
}: {
  proxy: ProxyOut | null;
  open: boolean;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}) {
  const { push } = useToast();
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState<ProxyUpdate>({
    url: "",
    country: "",
    timezone: "",
    notes: "",
    skip_health_check: false,
  });

  useEffect(() => {
    if (!proxy || !open) return;
    setForm({
      url: proxy.url,
      country: proxy.country ?? "",
      timezone: proxy.timezone ?? "",
      notes: proxy.notes ?? "",
      skip_health_check: false,
    });
  }, [proxy, open]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!proxy || !form.url.trim()) {
      push("Укажите URL", "error");
      return;
    }
    setBusy(true);
    try {
      const payload: ProxyUpdate = {
        url: form.url.trim(),
        country: form.country?.trim() ? form.country.trim() : null,
        timezone: form.timezone?.trim() ? form.timezone.trim() : null,
        notes: form.notes?.trim() ? form.notes : null,
        skip_health_check: form.skip_health_check,
      };
      await api.proxies.update(proxy.label, payload);
      await onSaved();
    } catch (err) {
      push((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  const label = proxy?.label ?? "";

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Изменить прокси · ${label}`}
      footer={
        <>
          <button type="button" onClick={onClose} className="btn-ghost">
            <XCircle size={16} /> Отмена
          </button>
          <button form="edit-proxy-form" type="submit" className="btn-primary" disabled={busy}>
            <CheckCircle2 size={16} />
            {busy ? "Сохранение…" : "Сохранить изменения"}
          </button>
        </>
      }
    >
      <form id="edit-proxy-form" onSubmit={submit} className="space-y-3">
        <div>
          <label className="label">URL</label>
          <input
            className="input font-mono text-sm"
            placeholder="http://user:pass@host:port"
            value={form.url}
            onChange={(e) => setForm({ ...form, url: e.target.value })}
          />
          <p className="text-xs text-slate-500 mt-1">
            Хранится в базе данных для этого рабочего пространства.
          </p>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label">Страна</label>
            <input
              className="input"
              maxLength={8}
              value={form.country ?? ""}
              onChange={(e) => setForm({ ...form, country: e.target.value })}
            />
            <p className="text-xs text-slate-500 mt-1">
              Необязательно: заполнится при проверке по IP
            </p>
          </div>
          <div>
            <label className="label">Часовой пояс</label>
            <input
              className="input"
              value={form.timezone ?? ""}
              onChange={(e) => setForm({ ...form, timezone: e.target.value })}
            />
            <p className="text-xs text-slate-500 mt-1">
              Необязательно: заполнится при проверке по IP
            </p>
          </div>
        </div>
        <div>
          <label className="label">Заметки</label>
          <textarea
            className="input min-h-[60px]"
            value={form.notes ?? ""}
            onChange={(e) => setForm({ ...form, notes: e.target.value })}
          />
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-300">
          <input
            type="checkbox"
            className="h-4 w-4 rounded border-slate-600 bg-slate-900"
            checked={form.skip_health_check}
            onChange={(e) =>
              setForm({ ...form, skip_health_check: e.target.checked })
            }
          />
          <span>Пропустить проверку после сохранения</span>
        </label>
      </form>
    </Modal>
  );
}

function AddProxyModal({
  open,
  onClose,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}) {
  const { push } = useToast();
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState<ProxyIn>({
    label: "",
    url: "",
    country: "",
    timezone: "",
    notes: "",
    skip_health_check: false,
  });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.label || !form.url) {
      push("Заполните метку и URL", "error");
      return;
    }
    setBusy(true);
    try {
      await api.proxies.create(form);
      await onSaved();
      setForm({ label: "", url: "", country: "", timezone: "", notes: "", skip_health_check: false });
    } catch (err) {
      push((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Добавить прокси"
      footer={
        <>
          <button onClick={onClose} className="btn-ghost">
            <XCircle size={16} /> Отмена
          </button>
          <button form="add-proxy-form" type="submit" className="btn-primary" disabled={busy}>
            <CheckCircle2 size={16} />
            {busy ? "Сохранение…" : "Сохранить прокси"}
          </button>
        </>
      }
    >
      <form id="add-proxy-form" onSubmit={submit} className="space-y-3">
        <div>
          <label className="label">Метка</label>
          <input
            className="input"
            value={form.label}
            onChange={(e) => setForm({ ...form, label: e.target.value })}
          />
        </div>
        <div>
          <label className="label">URL</label>
          <input
            className="input"
            placeholder="http://user:pass@host:port"
            value={form.url}
            onChange={(e) => setForm({ ...form, url: e.target.value })}
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label">Страна</label>
            <input
              className="input"
              maxLength={8}
              value={form.country ?? ""}
              onChange={(e) => setForm({ ...form, country: e.target.value })}
            />
            <p className="text-xs text-slate-500 mt-1">
              Необязательно: заполнится при проверке по IP
            </p>
          </div>
          <div>
            <label className="label">Часовой пояс</label>
            <input
              className="input"
              value={form.timezone ?? ""}
              onChange={(e) => setForm({ ...form, timezone: e.target.value })}
            />
            <p className="text-xs text-slate-500 mt-1">
              Необязательно: заполнится при проверке по IP
            </p>
          </div>
        </div>
        <div>
          <label className="label">Заметки</label>
          <textarea
            className="input min-h-[60px]"
            value={form.notes ?? ""}
            onChange={(e) => setForm({ ...form, notes: e.target.value })}
          />
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-300">
          <input
            type="checkbox"
            className="h-4 w-4 rounded border-slate-600 bg-slate-900"
            checked={form.skip_health_check}
            onChange={(e) =>
              setForm({ ...form, skip_health_check: e.target.checked })
            }
          />
          <span>Пропустить проверку при сохранении</span>
        </label>
      </form>
    </Modal>
  );
}
