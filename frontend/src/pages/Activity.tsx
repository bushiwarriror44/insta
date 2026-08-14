import { Ban, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import { Card } from "../components/Card";
import { DiagnosticLogPanel } from "../components/DiagnosticLogPanel";
import { Loader } from "../components/Loader";
import { Modal } from "../components/Modal";
import { StatusBadge } from "../components/StatusBadge";
import { useToast } from "../context/ToastContext";
import type { DiagnosticRunOut, EventOut, JobOut } from "../api/types";

const POLL_INTERVAL_MS = 7000;
const JOB_LOG_POLL_MS = 3000;

const POST_TYPE_LABELS: Record<string, string> = {
  reel: "Reels",
  feed_photo: "Фото в ленте",
  feed_video: "Видео в ленте",
};

const JOB_STATUS_LABELS: Record<string, string> = {
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

const JOB_STATUSES = ["", "queued", "running", "done", "failed", "dead", "cancelled"];
const EVENT_LEVELS = ["", "info", "warn", "error", "critical"];

function basename(path: string) {
  return path.split(/[\\/]/).pop() || path;
}

export function Activity() {
  const { push } = useToast();
  const [jobs, setJobs] = useState<JobOut[]>([]);
  const [events, setEvents] = useState<EventOut[]>([]);
  const [jobStatus, setJobStatus] = useState<string>("");
  const [eventLevel, setEventLevel] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [selectedJob, setSelectedJob] = useState<JobOut | null>(null);
  const [jobRuns, setJobRuns] = useState<DiagnosticRunOut[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
  const [logsLoading, setLogsLoading] = useState(false);

  const reload = useCallback(async () => {
    const [j, e] = await Promise.all([
      api.jobs.list({ status: jobStatus || undefined, limit: 100 }),
      api.events.list({ level: eventLevel || undefined, limit: 100 }),
    ]);
    setJobs(j);
    setEvents(e);
  }, [jobStatus, eventLevel]);

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

  useEffect(() => {
    let cancelled = false;
    let initial = true;
    async function tick() {
      try {
        await reload();
      } catch (err) {
        if (initial) push((err as Error).message, "error");
      } finally {
        if (initial) setLoading(false);
        initial = false;
      }
      if (cancelled) return;
    }
    tick();
    const id = window.setInterval(tick, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [reload, push]);

  useEffect(() => {
    setSelectedJob((prev) => {
      if (!prev) return prev;
      return jobs.find((j) => j.id === prev.id) ?? prev;
    });
  }, [jobs]);

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
          <div className="overflow-x-auto -mx-5">
            <table className="table-base">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Аккаунт</th>
                  <th>Тип</th>
                  <th>Статус</th>
                  <th>Запланировано</th>
                  <th>Следующая попытка</th>
                  <th>Попытки</th>
                  <th>Источник</th>
                  <th>Последняя ошибка</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((j) => (
                  <tr
                    key={j.id}
                    className="hover:bg-slate-900/40 align-top cursor-pointer"
                    onClick={() => setSelectedJob(j)}
                  >
                    <td className="tabular-nums text-slate-400">#{j.id}</td>
                    <td className="font-medium">
                      {j.account_username ? `@${j.account_username}` : `id:${j.account_id}`}
                    </td>
                    <td className="text-xs text-slate-400">{POST_TYPE_LABELS[j.post_type] ?? j.post_type}</td>
                    <td>
                      <StatusBadge value={j.status} />
                    </td>
                    <td className="text-xs text-slate-400">
                      {new Date(j.scheduled_for).toLocaleString("ru-RU")}
                    </td>
                    <td className="text-xs text-slate-400">
                      {j.next_attempt_at ? new Date(j.next_attempt_at).toLocaleString("ru-RU") : "—"}
                    </td>
                    <td className="tabular-nums text-slate-300">{j.attempts}</td>
                    <td className="text-xs text-slate-400 max-w-[200px] break-all">
                      {basename(j.source_video_path)}
                    </td>
                    <td className="text-xs text-rose-300 max-w-[220px] break-words">
                      {j.last_error ?? ""}
                    </td>
                    <td className="text-right" onClick={(e) => e.stopPropagation()}>
                      {(j.status === "queued" || j.status === "failed") && (
                        <button
                          className="btn-ghost text-xs"
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
                          <Ban size={14} /> Отменить
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

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
            {events.map((ev) => (
              <li key={ev.id} className="flex items-start gap-3 py-3 text-sm">
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
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Modal
        open={selectedJob !== null}
        onClose={() => {
          setSelectedJob(null);
          setJobRuns([]);
          setSelectedRunId(null);
        }}
        title={selectedJob ? `Логи задачи #${selectedJob.id}` : "Логи задачи"}
        footer={
          <button type="button" className="btn-ghost" onClick={() => setSelectedJob(null)}>
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
