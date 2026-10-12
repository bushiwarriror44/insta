import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { api, formatApiError } from "../api/client";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { useToast } from "../context/ToastContext";
import { useAssistantMutate } from "../lib/assistantMutate";
import type { JobOut } from "../api/types";

function startOfWeek(now: Date): Date {
  const day = now.getDay();
  const mondayOffset = day === 0 ? -6 : 1 - day;
  const start = new Date(now);
  start.setHours(0, 0, 0, 0);
  start.setDate(start.getDate() + mondayOffset);
  return start;
}

function dayKey(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${dd}`;
}

function weekFromSearch(raw: string | null): number {
  if (raw == null || raw === "") return 0;
  const n = Number(raw);
  return Number.isFinite(n) ? Math.trunc(n) : 0;
}

export function Calendar() {
  const { push } = useToast();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [jobs, setJobs] = useState<JobOut[] | null>(null);
  const [dragId, setDragId] = useState<number | null>(null);
  const weekOffset = weekFromSearch(searchParams.get("week"));
  const setWeekOffset = useCallback(
    (next: number | ((prev: number) => number)) => {
      const value = typeof next === "function" ? next(weekOffset) : next;
      setSearchParams(
        (prev) => {
          const params = new URLSearchParams(prev);
          if (value === 0) params.delete("week");
          else params.set("week", String(value));
          return params;
        },
        { replace: true }
      );
    },
    [setSearchParams, weekOffset]
  );
  const weekStart = useMemo(() => {
    const start = startOfWeek(new Date());
    start.setDate(start.getDate() + weekOffset * 7);
    return start;
  }, [weekOffset]);
  const days = useMemo(
    () =>
      Array.from({ length: 7 }, (_, i) => {
        const day = new Date(weekStart);
        day.setDate(weekStart.getDate() + i);
        return day;
      }),
    [weekStart]
  );

  const load = useCallback(async () => {
    try {
      setJobs(await api.jobs.list({ limit: 200 }));
    } catch (err) {
      push(formatApiError(err), "error");
    }
  }, [push]);

  useAssistantMutate(load);

  useEffect(() => {
    void load();
  }, [load]);

  const byDay = useMemo(() => {
    const map: Record<string, JobOut[]> = {};
    for (const day of days) map[dayKey(day)] = [];
    for (const job of jobs ?? []) {
      if (job.status === "cancelled") continue;
      const key = dayKey(new Date(job.scheduled_for));
      if (map[key]) map[key].push(job);
    }
    return map;
  }, [jobs, days]);

  async function dropOn(day: Date) {
    if (dragId == null) return;
    const job = jobs?.find((row) => row.id === dragId);
    const when = new Date(day);
    if (job?.scheduled_for) {
      const original = new Date(job.scheduled_for);
      when.setHours(original.getHours(), original.getMinutes(), original.getSeconds(), original.getMilliseconds());
    } else {
      when.setHours(12, 0, 0, 0);
    }
    try {
      await api.jobs.reschedule(dragId, when.toISOString());
      await load();
    } catch (err) {
      push(formatApiError(err), "error");
    } finally {
      setDragId(null);
    }
  }

  const heading = weekStart.toLocaleDateString("ru-RU", { day: "numeric", month: "long" });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <PageHeader
          icon={CalendarDays}
          title="Календарь"
          description="Время этого компьютера. Перетаскивание сохраняет час публикации."
        />
        <div className="flex items-center gap-2">
          <button type="button" className="btn-ghost text-xs" onClick={() => setWeekOffset((n) => n - 1)}>
            <ChevronLeft className="h-4 w-4" />
            Назад
          </button>
          <span className="text-sm text-slate-400">неделя с {heading}</span>
          <button type="button" className="btn-ghost text-xs" onClick={() => setWeekOffset(0)}>
            Сегодня
          </button>
          <button type="button" className="btn-ghost text-xs" onClick={() => setWeekOffset((n) => n + 1)}>
            Вперёд
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-7 gap-3">
        {days.map((day) => (
          <div
            key={dayKey(day)}
            data-testid={`calendar-day-${dayKey(day)}`}
            className="card p-3 min-h-[220px]"
            onDragOver={(e) => e.preventDefault()}
            onDrop={() => void dropOn(day)}
          >
            <div className="text-xs text-slate-400 mb-2">
              {day.toLocaleDateString("ru-RU", { weekday: "short", day: "numeric", month: "short" })}
            </div>
            <div className="space-y-2">
              {(byDay[dayKey(day)] ?? []).map((job) => (
                <div
                  id={`job-${job.id}`}
                  key={job.id}
                  draggable={!["done", "failed", "dead"].includes(job.status)}
                  onClick={(event) => {
                    event.stopPropagation();
                    if (dragId != null) return;
                    navigate(`/activity?job=${job.id}`);
                  }}
                  onDragStart={() => {
                    if (["done", "failed", "dead"].includes(job.status)) return;
                    setDragId(job.id);
                  }}
                  onDragEnd={() => setDragId(null)}
                  className="rounded-lg border border-slate-800 bg-slate-900/60 p-2 text-xs cursor-grab hover:border-slate-700 transition-colors"
                >
                  <div className="font-medium truncate">{job.title || job.account_username}</div>
                  <div className="mt-1 tabular-nums text-slate-400">
                    {new Date(job.scheduled_for).toLocaleTimeString("ru-RU", {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </div>
                  <div className="mt-1">
                    <StatusBadge value={job.status} />
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
