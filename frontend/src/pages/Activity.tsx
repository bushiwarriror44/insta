import { Ban, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import clsx from "clsx";

import { api } from "../api/client";
import { Card } from "../components/Card";
import { DiagnosticLogPanel } from "../components/DiagnosticLogPanel";
import { Loader } from "../components/Loader";
import { Modal } from "../components/Modal";
import { StatusBadge } from "../components/StatusBadge";
import { useToast } from "../context/ToastContext";
import { useHotkeys } from "../hooks/useHotkeys";
import { usePollWhenVisible } from "../hooks/usePollWhenVisible";
import { useAssistantMutate } from "../lib/assistantMutate";
import type { DiagnosticRunOut, EventOut, JobOut } from "../api/types";

const POLL_INTERVAL_MS = 7000;
const JOB_LOG_POLL_MS = 3000;

const POST_TYPE_LABELS: Record<string, string> = {
  reel: "Reels",
  feed_photo: "Фото в ленте",
  feed_video: "Видео в ленте",
  youtube_short: "YouTube Shorts",
  tiktok: "TikTok",
};

const JOB_STATUS_LABELS: Record<string, string> = {
  awaiting_review: "на проверке",
  queued: "в очереди",
  running: "выполняется",
  done: "завершена",
  failed: "ошибка",
  dead: "прервана",
  cancelled: "отменена",
};

const DIAG_RUN_STATUS_LABELS: Record<string, string> = {
  running: "выполняется",
  ok: "OK",
  warn: "предупреждение",
  fail: "ошибка",
};

const EVENT_LEVEL_LABELS: Record<string, string> = {
  info: "инфо",
  warn: "предупреждение",
  error: "ошибка",
  critical: "критическая",
};

const JOB_STATUSES = ["", "awaiting_review", "queued", "running", "done", "failed", "dead", "cancelled"];
const EVENT_LEVELS = ["", "info", "warn", "error", "critical"];

function basename(path: string) {
  return path.split(/[\\/]/).pop() || path;
}

function eventHref(ev: Pick<EventOut, "account_username" | "account_id">): string | null {
  if (ev.account_username) {
    return `/accounts?username=${encodeURIComponent(ev.account_username)}`;
  }
  if (ev.account_id) {
    return `/accounts?id=${ev.account_id}`;
  }
  return null;
}

export function Activity() {
  const { push } = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const statusFromUrl = (() => {
    const status = searchParams.get("status") || "";
    return JOB_STATUSES.includes(status) ? status : "";
  })();
  const jobFromUrl = Number(searchParams.get("job") || 0);
  const [jobs, setJobs] = useState<JobOut[]>([]);
  const [events, setEvents] = useState<EventOut[]>([]);
  const [jobStatus, setJobStatus] = useState(statusFromUrl);
  const [eventLevel, setEventLevel] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [selectedJob, setSelectedJob] = useState<JobOut | null>(null);
  const [jobRuns, setJobRuns] = useState<DiagnosticRunOut[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
  const [logsLoading, setLogsLoading] = useState(false);
  const [lane, setLane] = useState<"publishes" | "renders" | "joins">("publishes");
  const [renders, setRenders] = useState<Array<{ id: number; status: string; prompt: string; post_title: string; last_error: string | null }>>([]);
  const [joins, setJoins] = useState<Array<{ id: number; status: string; post_title: string; last_error: string | null; clips: number }>>([]);
  const [cursor, setCursor] = useState(0);
  const initialError = useRef({ shown: false });

  useEffect(() => {
    setJobStatus(statusFromUrl);
  }, [statusFromUrl]);

  const reload = useCallback(async () => {
    const [j, e] = await Promise.all([
      api.jobs.list({ status: jobStatus || undefined, limit: 100 }),
      api.events.list({ level: eventLevel || undefined, limit: 100 }),
    ]);
    setJobs(j);
    setEvents(e);
    if (lane !== "publishes") {
      const [g, c] = await Promise.all([api.factory.generations(), api.factory.compositions()]);
      setRenders(g);
      setJoins(c);
    }
  }, [jobStatus, eventLevel, lane]);

  useAssistantMutate(reload);

  const loadJobLogs = useCallback(async (jobId: number) => {
    setLogsLoading(true);
    try {
      const runs = await api.jobs.logs(jobId);
      setJobRuns(runs);
      setSelectedRunId((current) => {
        if (current && runs.some((r) => r.id === current)) return current;
        return runs.length > 0 ? runs[runs.length - 1].id : null;
      });
    } catch (err) {
      push((err as Error).message, "error");
      setJobRuns([]);
      setSelectedRunId(null);
    } finally {
      setLogsLoading(false);
    }
  }, [push]);

  const poll = useCallback(async () => {
    try {
      await reload();
    } catch (err) {
      if (!initialError.current.shown) {
        initialError.current.shown = true;
        push((err as Error).message, "error");
      }
    } finally {
      setLoading(false);
    }
  }, [push, reload]);
  usePollWhenVisible(poll, POLL_INTERVAL_MS, true, `${jobStatus}|${eventLevel}|${lane}`);

  const activityKeys = useMemo(
    () => ({
      j: () => {
        if (lane !== "publishes") return;
        setCursor((i) => Math.min(i + 1, Math.max(jobs.length - 1, 0)));
      },
      k: () => {
        if (lane !== "publishes") return;
        setCursor((i) => Math.max(i - 1, 0));
      },
      enter: () => {
        if (lane !== "publishes") return;
        const row = jobs[cursor];
        if (row) setSelectedJob(row);
      },
    }),
    [cursor, jobs, lane]
  );
  useHotkeys(activityKeys, !selectedJob);

  const closeLogs = useCallback(() => {
    setSelectedJob(null);
    setJobRuns([]);
    setSelectedRunId(null);
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete("job");
        return next;
      },
      { replace: true }
    );
  }, [setSearchParams]);

  useEffect(() => {
    setSelectedJob((prev) => {
      if (jobFromUrl) {
        return jobs.find((j) => j.id === jobFromUrl) ?? prev;
      }
      if (!prev) return prev;
      return jobs.find((j) => j.id === prev.id) ?? prev;
    });
  }, [jobs, jobFromUrl]);

  useEffect(() => {
    if (!selectedJob) return;
    loadJobLogs(selectedJob.id);
    const id = window.setInterval(() => {
      loadJobLogs(selectedJob.id);
      if (selectedJob.status === "running") {
        reload();
      }
    }, JOB_LOG_POLL_MS);
    return () => window.clearInterval(id);
  }, [selectedJob, loadJobLogs, reload]);

  const activeRun =
    jobRuns.find((r) => r.id === selectedRunId) ?? jobRuns[jobRuns.length - 1] ?? null;
  const activeLines = activeRun?.logs ?? [];

  if (loading) return <Loader />;

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold">Активность</h1>
          <p className="text-sm text-slate-400 mt-1">
            Очередь задач и журнал событий в реальном времени. Обновление каждые {POLL_INTERVAL_MS / 1000} с.
          </p>
        </div>
        <button
          className="btn-ghost"
          onClick={async () => {
            try {
              await reload();
              push("Обновлено", "info");
            } catch (err) {
              push((err as Error).message, "error");
            }
          }}
        >
          <RefreshCw size={16} /> Обновить сейчас
        </button>
      </div>

      <div className="flex gap-2">
        {(
          [
            ["publishes", "Публикации"],
            ["renders", "Рендеры"],
            ["joins", "Склейки"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            className={lane === id ? "btn-primary" : "btn-ghost"}
            onClick={() => setLane(id)}
          >
            {label}
          </button>
        ))}
      </div>

      {lane === "publishes" ? (
      <Card
        title="Задачи"
        description={`${jobs.length} последних — нажмите на строку для просмотра диагностических логов`}
        actions={
          <select
            className="input max-w-[140px] py-1.5 text-xs"
            value={jobStatus}
            onChange={(e) => setJobStatus(e.target.value)}
          >
            {JOB_STATUSES.map((s) => (
              <option key={s} value={s}>
                {s ? (JOB_STATUS_LABELS[s] ?? s) : "Все статусы"}
              </option>
            ))}
          </select>
        }
      >
        {jobs.length === 0 ? (
          <div className="text-sm text-slate-500">Нет задач по выбранному фильтру.</div>
        ) : (
          <table className="table-base">
            <colgroup>
              <col className="w-[8%]" />
              <col className="w-[12%]" />
              <col className="w-[10%]" />
              <col className="w-[10%]" />
              <col className="w-[16%]" />
              <col className="w-[6%]" />
              <col className="w-[14%]" />
              <col className="w-[14%]" />
              <col className="w-[10%]" />
            </colgroup>
            <thead>
              <tr>
                <th>ID</th>
                <th>Аккаунт</th>
                <th>Тип</th>
                <th>Статус</th>
                <th>Когда</th>
                <th>Поп.</th>
                <th>Источник</th>
                <th>Ошибка</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((j) => (
                <tr
                  key={j.id}
                  aria-label={`Задача #${j.id} @${j.account_username ?? j.account_id}`}
                  className={clsx(
                    "hover:bg-slate-900/40 align-top cursor-pointer",
                    jobs[cursor]?.id === j.id && "bg-white/[0.05]"
                  )}
                  onClick={() => {
                    setSelectedJob(j);
                    setCursor(jobs.findIndex((row) => row.id === j.id));
                  }}
                >
                  <td className="tabular-nums text-slate-400">#{j.id}</td>
                  <td className="font-medium truncate" title={j.account_username ? `@${j.account_username}` : `id:${j.account_id}`}>
                    {j.account_username ? `@${j.account_username}` : `id:${j.account_id}`}
                  </td>
                  <td className="text-[11px] text-slate-400 truncate">
                    {POST_TYPE_LABELS[j.post_type] ?? j.post_type}
                  </td>
                  <td>
                    <StatusBadge value={j.status} />
                  </td>
                  <td className="text-[11px] text-slate-400">
                    <div className="truncate" title={new Date(j.scheduled_for).toLocaleString("ru-RU")}>
                      {new Date(j.scheduled_for).toLocaleString("ru-RU")}
                    </div>
                    <div className="truncate text-slate-500" title={j.next_attempt_at ? new Date(j.next_attempt_at).toLocaleString("ru-RU") : ""}>
                      {j.next_attempt_at ? new Date(j.next_attempt_at).toLocaleString("ru-RU") : "—"}
                    </div>
                  </td>
                  <td className="tabular-nums text-slate-300">{j.attempts}</td>
                  <td className="text-[11px] text-slate-400 truncate" title={basename(j.source_video_path)}>
                    {basename(j.source_video_path)}
                  </td>
                  <td className="text-[11px] text-rose-300 truncate" title={j.last_error ?? ""}>
                    {j.last_error ?? ""}
                  </td>
                  <td className="text-right" onClick={(e) => e.stopPropagation()}>
                    <div className="flex justify-end gap-1 flex-wrap">
                      {j.status === "awaiting_review" && (
                        <button
                          className="btn-primary btn-compact"
                          onClick={async () => {
                            try {
                              const upd = await api.jobs.approve(j.id);
                              setJobs((arr) => arr.map((x) => (x.id === upd.id ? upd : x)));
                              push(`Задача #${j.id} одобрена`, "success");
                            } catch (err) {
                              push((err as Error).message, "error");
                            }
                          }}
                        >
                          Одобрить
                        </button>
                      )}
                      {(j.status === "queued" || j.status === "failed" || j.status === "awaiting_review") && (
                        <button
                          className="btn-ghost btn-compact"
                          aria-label="Отменить"
                          onClick={async () => {
                            try {
                              const upd = await api.jobs.cancel(j.id);
                              setJobs((arr) =>
                                arr.map((x) => (x.id === upd.id ? upd : x))
                              );
                              push(`Задача #${j.id} отменена`, "info");
                            } catch (err) {
                              push((err as Error).message, "error");
                            }
                          }}
                        >
                          <Ban size={14} />
                        </button>
                      )}
                      {(j.status === "failed" || j.status === "dead" || j.status === "cancelled") && (
                        <button
                          className="btn-ghost btn-compact"
                          onClick={async () => {
                            try {
                              const upd = await api.jobs.retry(j.id);
                              setJobs((arr) => arr.map((x) => (x.id === upd.id ? upd : x)));
                              push(`Задача #${j.id} снова в очереди`, "success");
                            } catch (err) {
                              push((err as Error).message, "error");
                            }
                          }}
                        >
                          Повторить
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      ) : lane === "renders" ? (
        <Card title="Рендеры">
          {renders.length === 0 ? (
            <div className="text-sm text-slate-500">Нет рендеров.</div>
          ) : (
            <ul className="text-sm space-y-2">
              {renders.map((g) => (
                <li key={g.id} className="flex justify-between gap-2 border-t border-slate-800 pt-2">
                  <span>#{g.id} {g.post_title || g.prompt.slice(0, 50)}</span>
                  <StatusBadge value={g.status} />
                </li>
              ))}
            </ul>
          )}
        </Card>
      ) : (
        <Card title="Склейки">
          {joins.length === 0 ? (
            <div className="text-sm text-slate-500">Нет склеек.</div>
          ) : (
            <ul className="text-sm space-y-2">
              {joins.map((g) => (
                <li key={g.id} className="flex justify-between gap-2 border-t border-slate-800 pt-2">
                  <span>#{g.id} {g.post_title} · {g.clips} клипов</span>
                  <StatusBadge value={g.status} />
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      <Card
        title="События"
        description={`${events.length} последних`}
        actions={
          <select
            className="input max-w-[140px] py-1.5 text-xs"
            value={eventLevel}
            onChange={(e) => setEventLevel(e.target.value)}
          >
            {EVENT_LEVELS.map((l) => (
              <option key={l} value={l}>
                {l ? (EVENT_LEVEL_LABELS[l] ?? l) : "Все уровни"}
              </option>
            ))}
          </select>
        }
      >
        {events.length === 0 ? (
          <div className="text-sm text-slate-500">Событий нет.</div>
        ) : (
          <ul className="divide-y divide-slate-800">
            {events.map((ev) => {
              const href = eventHref(ev);
              const body = (
                <>
                  <StatusBadge value={ev.level} />
                  <div className="flex-1 min-w-0">
                    <div className="flex flex-wrap items-baseline gap-2">
                      <span className="font-medium">{ev.kind}</span>
                      {ev.account_username && (
                        <span className="text-slate-400 text-xs">@{ev.account_username}</span>
                      )}
                      <span className="ml-auto text-xs text-slate-500">
                        {new Date(ev.created_at).toLocaleString("ru-RU")}
                      </span>
                    </div>
                    <div className="text-slate-300 mt-0.5 break-words">{ev.message}</div>
                  </div>
                </>
              );
              return (
                <li key={ev.id} className="py-3 text-sm">
                  {href ? (
                    <Link
                      to={href}
                      className="flex items-start gap-3 rounded-md hover:bg-slate-900/60 -mx-1 px-1"
                    >
                      {body}
                    </Link>
                  ) : (
                    <div className="flex items-start gap-3 -mx-1 px-1">{body}</div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </Card>

      <Modal
        open={selectedJob !== null}
        onClose={closeLogs}
        title={selectedJob ? `Логи задачи #${selectedJob.id}` : "Логи задачи"}
        footer={
          <button type="button" className="btn-ghost" onClick={closeLogs}>
            Закрыть
          </button>
        }
      >
        {selectedJob ? (
          <div className="space-y-4">
            <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3 text-sm space-y-1">
              <div>
                Аккаунт:{" "}
                <span className="font-medium">
                  {selectedJob.account_username
                    ? `@${selectedJob.account_username}`
                    : selectedJob.account_id}
                </span>
              </div>
              <div className="text-slate-400">
                {POST_TYPE_LABELS[selectedJob.post_type] ?? selectedJob.post_type} · {basename(selectedJob.source_video_path)} · попыток{" "}
                {selectedJob.attempts}
              </div>
              <div className="flex items-center gap-2">
                <StatusBadge value={selectedJob.status} />
                {selectedJob.last_error ? (
                  <span className="text-xs text-rose-300">{selectedJob.last_error}</span>
                ) : null}
              </div>
            </div>

            {jobRuns.length > 1 ? (
              <select
                className="input text-xs"
                value={selectedRunId ?? ""}
                onChange={(e) => setSelectedRunId(Number(e.target.value))}
              >
                {jobRuns.map((run, idx) => (
                  <option key={run.id} value={run.id}>
                    Попытка {idx + 1} — {DIAG_RUN_STATUS_LABELS[run.status] ?? run.status}
                    {run.summary ? ` — ${run.summary}` : ""}
                  </option>
                ))}
              </select>
            ) : null}

            {logsLoading && activeLines.length === 0 ? (
              <Loader label="Загрузка логов…" />
            ) : (
              <DiagnosticLogPanel
                lines={activeLines}
                emptyLabel="Диагностические логи для этой задачи пока отсутствуют."
                maxHeightClass="max-h-80"
              />
            )}
          </div>
        ) : null}
      </Modal>
    </div>
  );
}
