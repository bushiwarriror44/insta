import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { AssistantJobOut } from "../api/types";
import { showAssistant } from "../lib/uiEvents";

type ActiveJob = AssistantJobOut;

export function AgentRunOverlay() {
  const [job, setJob] = useState<ActiveJob | null>(null);
  const [pending, setPending] = useState(false);

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
    return () => {
      stop = true;
      window.clearInterval(timer);
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

  return (
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center bg-slate-950/75 backdrop-blur-sm"
      data-testid="agent-run-overlay"
      role="dialog"
      aria-modal="true"
      aria-label="агент выполняет задачу"
    >
      <div className="mx-4 w-full max-w-md rounded-2xl border border-slate-700 bg-slate-900 px-6 py-8 text-center shadow-2xl">
        <div className="mx-auto h-12 w-12 animate-spin rounded-full border-2 border-slate-600 border-t-brand-400" />
        <p className="mt-5 text-lg font-medium text-white">агент выполняет задачу</p>
        {job.note ? <p className="mt-2 text-sm text-slate-400">{job.note}</p> : null}
        <div className="mt-6 flex flex-col gap-2 sm:flex-row sm:justify-center">
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
