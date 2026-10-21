import { useCallback, useRef, useState } from "react";
import { Square, Play } from "lucide-react";
import clsx from "clsx";

import { api, formatApiError } from "../api/client";
import type { WorkerProcessOut } from "../api/types";
import { useToast } from "../context/ToastContext";
import { usePollWhenVisible } from "../hooks/usePollWhenVisible";

const POLL_MS = 8000;

const IDLE: WorkerProcessOut = {
  running: false,
  ours: false,
  pid: null,
  seen_at: null,
  note: "",
};

export function AgentToggle({ compact = false }: { compact?: boolean }) {
  const { push } = useToast();
  const [worker, setWorker] = useState<WorkerProcessOut | null>(null);
  const [busy, setBusy] = useState(false);
  const seenRunning = useRef<boolean | null>(null);
  const stoppedByUs = useRef(false);

  const applyStatus = useCallback(
    (next: WorkerProcessOut) => {
      if (
        compact &&
        seenRunning.current === true &&
        !next.running &&
        !stoppedByUs.current
      ) {
        push("Воркер остановился", "error", { label: "Открыть", href: "/activity" });
      }
      seenRunning.current = next.running;
      if (!next.running) stoppedByUs.current = false;
      setWorker(next);
    },
    [compact, push]
  );

  const reload = useCallback(async () => {
    try {
      applyStatus(await api.worker.status());
    } catch (err) {
      if (!compact) push(formatApiError(err), "error");
    }
  }, [applyStatus, compact, push]);

  usePollWhenVisible(reload, POLL_MS);

  const current = worker ?? IDLE;

  async function run(action: "start" | "stop") {
    if (action === "stop" && !window.confirm("Остановить воркер очереди?")) return;
    setBusy(true);
    try {
      if (action === "stop") stoppedByUs.current = true;
      const next =
        action === "start" ? await api.worker.start() : await api.worker.stop();
      applyStatus(next);
      push(action === "start" ? "Агент запущен" : "Агент остановлен", "success");
    } catch (err) {
      stoppedByUs.current = false;
      push(formatApiError(err), "error");
      await reload();
    } finally {
      setBusy(false);
    }
  }

  const canStop = current.ours;
  const canStart = !current.ours && !current.running;
  const foreign = current.running && !current.ours;

  const statusLabel = current.running
    ? current.ours
      ? current.pid
        ? `Агент работает · pid ${current.pid}`
        : "Агент работает"
      : compact
        ? "Воркер снаружи"
        : "Воркер Docker / терминал"
    : "Агент остановлен";

  const seenLabel = current.seen_at
    ? `Последний цикл ${new Date(current.seen_at).toLocaleString("ru-RU")}`
    : null;
  const foreignHint =
    "Compose поднимает reels-worker сам. Стоп в панели — только для процесса, который запустила панель.";
  const compactTitle = [
    statusLabel,
    seenLabel,
    current.note || null,
    foreign ? foreignHint : null,
  ]
    .filter(Boolean)
    .join(" · ");

  if (compact) {
    return (
      <div className="flex items-center gap-2" title={compactTitle}>
        <span
          className={clsx(
            "h-2 w-2 rounded-full",
            current.running ? "bg-emerald-400 animate-pulse" : "bg-rose-400"
          )}
        />
        <span className="text-xs text-slate-400 hidden sm:inline">{statusLabel}</span>
        {canStop ? (
          <button
            type="button"
            className="btn-ghost text-xs py-1 px-2"
            disabled={busy}
            onClick={() => void run("stop")}
          >
            {busy ? "…" : "Стоп"}
          </button>
        ) : canStart ? (
          <button
            type="button"
            className="btn-ghost text-xs py-1 px-2"
            disabled={busy}
            onClick={() => void run("start")}
          >
            {busy ? "…" : "Старт"}
          </button>
        ) : null}
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-3">
      <span
        className={clsx(
          "h-2.5 w-2.5 shrink-0 rounded-full",
          current.running ? "bg-emerald-400 animate-pulse" : "bg-rose-400"
        )}
      />
      <div className="flex-1 min-w-[12rem]">
        <div className="text-sm">{statusLabel}</div>
        <div className="text-xs text-slate-500">
          {seenLabel
            ? seenLabel
            : "Ещё не отмечался в этой базе. Без агента план, fal и публикация не идут."}
        </div>
      </div>
      {canStop ? (
        <button type="button" className="btn-ghost" disabled={busy} onClick={() => void run("stop")}>
          <Square size={14} />
          {busy ? "Останавливаем…" : "Остановить"}
        </button>
      ) : (
        <button
          type="button"
          className="btn-primary"
          disabled={busy || current.running}
          onClick={() => void run("start")}
        >
          <Play size={14} />
          {busy ? "Запускаем…" : "Запустить"}
        </button>
      )}
      {foreign ? (
        <p className="w-full text-xs text-slate-500">{foreignHint}</p>
      ) : null}
    </div>
  );
}
