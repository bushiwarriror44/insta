import {
  Activity as ActivityIcon,
  AlertTriangle,
  CheckCircle2,
  Server,
  Users,
} from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import { Card } from "../components/Card";
import { Loader } from "../components/Loader";
import { StatCard } from "../components/StatCard";
import { StatusBadge } from "../components/StatusBadge";
import { useToast } from "../context/ToastContext";
import type { DashboardSummary } from "../api/types";

const POLL_INTERVAL_MS = 8000;

function formatDate(value: string) {
  return new Date(value).toLocaleString("ru-RU");
}

export function Dashboard() {
  const { push } = useToast();
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    let initial = true;
    async function tick() {
      try {
        const summary = await api.dashboard();
        if (cancelled) return;
        setData(summary);
      } catch (err) {
        if (initial) push((err as Error).message, "error");
      } finally {
        if (initial) setLoading(false);
        initial = false;
      }
    }
    tick();
    const id = window.setInterval(tick, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [push]);

  if (loading || !data) return <Loader />;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Панель</h1>
        <p className="text-sm text-slate-400 mt-1">Текущее состояние аккаунтов и очереди.</p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Активные аккаунты"
          value={`${data.accounts_active} / ${data.accounts_total}`}
          icon={Users}
          tone="success"
          hint={data.accounts_blocked ? `${data.accounts_blocked} заблокировано` : "блокировок нет"}
        />
        <StatCard
          label="Исправные прокси"
          value={`${data.proxies_healthy} / ${data.proxies_total}`}
          icon={Server}
          tone={data.proxies_total === 0 ? "warn" : "info"}
        />
        <StatCard
          label="В очереди / В работе"
          value={`${data.jobs_queued} · ${data.jobs_running}`}
          icon={ActivityIcon}
          tone="info"
          hint={`сегодня готово: ${data.jobs_done_today}`}
        />
        <StatCard
          label="Мёртвые задачи (всего)"
          value={data.jobs_dead_total}
          icon={data.jobs_dead_total ? AlertTriangle : CheckCircle2}
          tone={data.jobs_dead_total ? "danger" : "success"}
          hint={`риск 24ч: ${data.risk_signals_24h} · карантин: ${data.quarantined_accounts}`}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card title="Сегодня по аккаунтам" className="lg:col-span-1">
          {data.daily_stats.length === 0 ? (
            <div className="text-sm text-slate-500">Сегодня активности пока нет.</div>
          ) : (
            <ul className="divide-y divide-slate-800">
              {data.daily_stats.map((row) => (
                <li
                  key={row.username}
                  className="flex items-center justify-between py-2.5 text-sm"
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
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Последние события" className="lg:col-span-2">
          {data.recent_events.length === 0 ? (
            <div className="text-sm text-slate-500">Событий пока нет.</div>
          ) : (
            <ul className="divide-y divide-slate-800">
              {data.recent_events.map((ev) => (
                <li
                  key={ev.id}
                  className="flex items-start gap-3 py-3 text-sm"
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
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
