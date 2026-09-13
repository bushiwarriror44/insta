import {
  Activity as ActivityIcon,
  AlertTriangle,
  CheckCircle2,
  LayoutDashboard,
  RefreshCw,
  Server,
  Users,
} from "lucide-react";
import { useCallback, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { api, formatApiError } from "../api/client";
import { Card } from "../components/Card";
import { EmptyState } from "../components/EmptyState";
import { Loader } from "../components/Loader";
import { PageHeader } from "../components/PageHeader";
import { StatCard } from "../components/StatCard";
import { StatusBadge } from "../components/StatusBadge";
import { useToast } from "../context/ToastContext";
import { usePollWhenVisible } from "../hooks/usePollWhenVisible";
import { useAssistantMutate } from "../lib/assistantMutate";
import type { DashboardSummary, EventOut } from "../api/types";

const POLL_INTERVAL_MS = 8000;

function eventHref(ev: Pick<EventOut, "account_username" | "account_id">) {
  if (ev.account_username) {
    return `/accounts?username=${encodeURIComponent(ev.account_username)}`;
  }
  if (ev.account_id) {
    return `/accounts?id=${ev.account_id}`;
  }
  return "/activity";
}

function formatDate(value: string) {
  return new Date(value).toLocaleString("ru-RU");
}

export function Dashboard() {
  const { push } = useToast();
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const hasDataRef = useRef(false);

  const refresh = useCallback(async (opts?: { isInitial?: boolean }) => {
    const isInitial = opts?.isInitial ?? false;
    try {
      const summary = await api.dashboard();
      hasDataRef.current = true;
      setData(summary);
      setLoadError(null);
    } catch (err) {
      const message = formatApiError(err);
      if (!hasDataRef.current) {
        setLoadError(message);
        if (isInitial) push(message, "error");
      }
    } finally {
      if (isInitial || !hasDataRef.current) setLoading(false);
    }
  }, [push]);

  useAssistantMutate(() => refresh());

  const poll = useCallback(() => refresh({ isInitial: !hasDataRef.current }), [refresh]);
  usePollWhenVisible(poll, POLL_INTERVAL_MS);

  if (loading && !data) return <Loader />;

  if (!data && loadError) {
    return (
      <div className="min-h-[40vh] grid place-items-center">
        <div className="card w-full max-w-md p-8 space-y-4 text-center">
          <h1 className="text-xl font-semibold">Не удалось загрузить панель</h1>
          <p className="text-sm text-slate-400 break-words">{loadError}</p>
          <button
            type="button"
            className="btn-primary w-full"
            onClick={() => {
              setLoading(true);
              setLoadError(null);
              hasDataRef.current = false;
              void refresh({ isInitial: true });
            }}
          >
            <RefreshCw size={16} />
            Повторить
          </button>
        </div>
      </div>
    );
  }

  if (!data) return <Loader />;

  return (
    <div className="space-y-6">
      <PageHeader
        icon={LayoutDashboard}
        title="Панель"
        description="Текущее состояние аккаунтов и очереди."
      />

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Активные аккаунты"
          value={`${data.accounts_active} / ${data.accounts_total}`}
          icon={Users}
          tone="success"
          hint={data.accounts_blocked ? `${data.accounts_blocked} заблокировано` : "блокировок нет"}
          to="/accounts"
        />
        <StatCard
          label="Исправные прокси"
          value={`${data.proxies_healthy} / ${data.proxies_total}`}
          icon={Server}
          tone={data.proxies_total === 0 ? "warn" : "info"}
          to="/accounts"
        />
        <StatCard
          label="В очереди / В работе"
          value={`${data.jobs_queued} · ${data.jobs_running}`}
          icon={ActivityIcon}
          tone="info"
          hint={`сегодня готово: ${data.jobs_done_today}`}
          to="/activity?status=queued"
        />
        <StatCard
          label="Мёртвые задачи (всего)"
          value={data.jobs_dead_total}
          icon={data.jobs_dead_total ? AlertTriangle : CheckCircle2}
          tone={data.jobs_dead_total ? "danger" : "success"}
          hint={`риск 24ч: ${data.risk_signals_24h} · карантин: ${data.quarantined_accounts}`}
          to="/activity?status=dead"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card title="Сегодня по аккаунтам" className="lg:col-span-1">
          {data.daily_stats.length === 0 ? (
            <EmptyState>Сегодня активности пока нет.</EmptyState>
          ) : (
            <ul className="divide-y divide-slate-800">
              {data.daily_stats.map((row) => (
                <li key={row.username} className="py-2.5 text-sm">
                  <Link
                    to={`/accounts?username=${encodeURIComponent(row.username)}`}
                    className="flex items-center justify-between gap-2 rounded-md hover:bg-slate-900/60 -mx-1 px-1"
                  >
                    <span className="font-medium">@{row.username}</span>
                    <span className="text-slate-400">
                      посты <span className="text-emerald-300 tabular-nums">{row.posts_count}</span>
                      {"  ·  "}
                      сбои{" "}
                      <span
                        className={
                          row.failures_count
                            ? "text-rose-300 tabular-nums"
                            : "text-slate-400 tabular-nums"
                        }
                      >
                        {row.failures_count}
                      </span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Последние события" className="lg:col-span-2">
          {data.recent_events.length === 0 ? (
            <EmptyState>Событий пока нет.</EmptyState>
          ) : (
            <ul className="divide-y divide-slate-800">
              {data.recent_events.map((ev) => {
                const href = eventHref(ev);
                return (
                  <li key={ev.id} className="py-3 text-sm">
                    <Link
                      to={href}
                      className="flex items-start gap-3 rounded-md hover:bg-slate-900/60 -mx-1 px-1"
                    >
                      <StatusBadge value={ev.level} />
                      <div className="flex-1 min-w-0">
                        <div className="flex flex-wrap items-baseline gap-2">
                          <span className="font-medium">{ev.kind}</span>
                          {ev.account_username && (
                            <span className="text-slate-400 text-xs">@{ev.account_username}</span>
                          )}
                          <span className="ml-auto text-xs text-slate-500">
                            {formatDate(ev.created_at)}
                          </span>
                        </div>
                        <div className="text-slate-300 mt-0.5 break-words">{ev.message}</div>
                      </div>
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
