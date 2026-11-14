import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { AssistantJobOut } from "../api/types";
import { showAssistant } from "../lib/uiEvents";

type ActiveJob = AssistantJobOut;

function elapsedLabel(createdAt: string, now: number): string {
  const start = Date.parse(createdAt);
  if (!Number.isFinite(start)) return "";
  const total = Math.max(0, Math.floor((now - start) / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  if (minutes <= 0) return `${seconds} с`;
  return `${minutes} мин ${String(seconds).padStart(2, "0")} с`;
}

export function AgentRunOverlay() {
  const [job, setJob] = useState<ActiveJob | null>(null);
  const [pending, setPending] = useState(false);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    let stop = false;
    const tick = async () => {
      try {
        const next = await api.assistantJobs.active();
        if (stop) return;
        if (
          next &&
          (next.status === "running" || next.status === "paused" || next.status === "needs_user")
        )
          setJob(next);
        else setJob(null);
      } catch {
        /* keep the last snapshot; the next tick retries */
      }
    };
    void tick();
    const timer = window.setInterval(() => void tick(), 500);
    const clock = window.setInterval(() => setNow(Date.now()), 1000);
    return () => {
      stop = true;
      window.clearInterval(timer);
      window.clearInterval(clock);
    };
  }, []);

  const act = async (kind: "pause" | "resume" | "stop") => {
    if (!job || pending) return;
    setPending(true);
    try {
      const next = await api.assistantJobs[kind](job.id);
      if (next.status === "running" || next.status === "paused") setJob(next);
      else setJob(null);
    } catch {
      /* the poll will catch up */
    } finally {
      setPending(false);
    }
  };

  const closeNeed = async () => {
    if (!job || pending) return;
    setPending(true);
    try {
      await api.assistantJobs.ack(job.id);
      setJob(null);
    } catch {
      /* the poll will catch up */
    } finally {
      setPending(false);
    }
  };

  if (!job) return null;

  if (job.status === "needs_user") {
    const text = job.note || job.reply || "Агенту нужно ваше действие.";
    return (
      <div
        className="fixed inset-0 z-[80] flex items-center justify-center bg-slate-950/75 backdrop-blur-sm"
        data-testid="agent-run-need"
        role="dialog"
        aria-modal="true"
        aria-label="агенту нужен человек"
      >
        <div className="mx-4 w-full max-w-md rounded-2xl border border-amber-400/40 bg-slate-900 px-6 py-8 text-center shadow-2xl">
          <p className="text-lg font-medium text-white">Нужен человек</p>
          <p className="mt-3 whitespace-pre-wrap text-sm text-slate-200">{text}</p>
          <div className="mt-6 flex flex-col gap-2 sm:flex-row sm:justify-center">
            <button
              type="button"
              className="btn-primary"
              data-testid="agent-run-open-chat"
              onClick={() => showAssistant()}
            >
              Открыть чат
            </button>
            <button
              type="button"
              className="btn-ghost"
              data-testid="agent-run-need-close"
              disabled={pending}
              onClick={() => void closeNeed()}
            >
              Закрыть
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (job.status === "paused") {
    return (
      <div
        className="fixed inset-x-0 top-0 z-[80] flex items-center justify-center gap-3 border-b border-amber-400/40 bg-amber-950/95 px-4 py-2 text-sm text-amber-50 shadow-lg"
        data-testid="agent-run-paused-bar"
        role="status"
      >
        <span>Агент на паузе</span>
        <button
          type="button"
          className="btn-primary px-3 py-1 text-xs"
          data-testid="agent-run-resume"
          disabled={pending}
          onClick={() => void act("resume")}
        >
          Продолжить
        </button>
        <button
          type="button"
          className="btn-danger px-3 py-1 text-xs"
          data-testid="agent-run-stop"
          disabled={pending}
          onClick={() => void act("stop")}
        >
          Остановить выполнение
        </button>
      </div>
    );
  }

  if (!job.acting) return null;

  const elapsed = elapsedLabel(job.created_at, now);

  return (
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center bg-slate-950/75 backdrop-blur-sm"
      data-testid="agent-run-overlay"
      role="dialog"
      aria-modal="true"
      aria-label="агент работает в панели"
    >
      <div className="mx-4 w-full max-w-lg rounded-2xl border border-slate-700 bg-slate-900 px-6 py-8 text-left shadow-2xl">
        <div className="flex items-start gap-4">
          <div className="mt-1 h-10 w-10 shrink-0 animate-spin rounded-full border-2 border-slate-600 border-t-brand-400" />
          <div className="min-w-0 flex-1">
            <p className="text-lg font-medium text-white">Агент работает в панели</p>
            {elapsed ? <p className="mt-1 text-xs text-slate-500">идёт {elapsed}</p> : null}
          </div>
        </div>
        {job.prompt ? (
          <p className="mt-5 line-clamp-4 text-sm leading-relaxed text-slate-200">{job.prompt}</p>
        ) : null}
        {job.activity ? (
          <p className="mt-4 rounded-lg border border-slate-800 bg-slate-950/70 px-3 py-2 text-sm text-slate-300">
            {job.activity}
          </p>
        ) : null}
        <div className="mt-6 flex flex-col gap-2 sm:flex-row sm:justify-end">
          <button
            type="button"
            className="btn-primary"
            data-testid="agent-run-pause"
            disabled={pending}
            onClick={() => void act("pause")}
          >
            Перехватить управление
          </button>
          <button
            type="button"
            className="btn-danger"
            data-testid="agent-run-stop"
            disabled={pending}
            onClick={() => void act("stop")}
          >
            Остановить выполнение
          </button>
        </div>
      </div>
    </div>
  );
}
