import { useCallback, useState } from "react";
import { Play, Square } from "lucide-react";
import clsx from "clsx";

import { api, formatApiError } from "../api/client";
import type { GpuOut } from "../api/types";
import { useToast } from "../context/ToastContext";
import { usePollWhenVisible } from "../hooks/usePollWhenVisible";

const POLL_MS = 8000;

const IDLE: GpuOut = {
  configured: false,
  status: null,
  billing: false,
  allocating_count: 0,
  creating_count: 0,
  running_count: 0,
  stopping_count: 0,
  chat_ok: false,
  detail: "",
};

const START_CONFIRM =
  "После Stop образ снова качается на узел. С Running идут GPU-часы. Запустить группу?";
const STOP_CONFIRM =
  "Часы остановятся, чат и local-видео лягут. Остановить группу Salad?";

function statusLabel(gpu: GpuOut): string {
  if (!gpu.configured) {
    return gpu.detail || "Salad не настроен";
  }
  switch (gpu.status) {
    case "running":
      return "Running — идут GPU-часы";
    case "deploying":
      return "Качается образ на узел";
    case "pending":
      return "Ждёт узел";
    case "stopped":
      return "Stopped — не тарится";
    case "failed":
      return "Failed";
    case "succeeded":
      return "Succeeded";
    default:
      return gpu.status ? gpu.status : "Статус неизвестен";
  }
}

function canStart(gpu: GpuOut): boolean {
  if (!gpu.configured) return false;
  return gpu.status === "stopped" || gpu.status === "succeeded" || gpu.status === "failed" || gpu.status == null;
}

function canStop(gpu: GpuOut): boolean {
  if (!gpu.configured) return false;
  return gpu.status === "running" || gpu.status === "pending" || gpu.status === "deploying";
}

export function SaladGpuCard() {
  const { push } = useToast();
  const [gpu, setGpu] = useState<GpuOut>(IDLE);
  const [busy, setBusy] = useState<"start" | "stop" | null>(null);
  const [loadError, setLoadError] = useState("");

  const reload = useCallback(async () => {
    try {
      const next = await api.gpu.status();
      if (!next || typeof next.configured !== "boolean") {
        throw new Error("Некорректный ответ /api/gpu");
      }
      setGpu(next);
      setLoadError("");
    } catch (err) {
      setLoadError(formatApiError(err));
    }
  }, []);

  usePollWhenVisible(reload, POLL_MS);

  async function run(action: "start" | "stop") {
    const ok = window.confirm(action === "start" ? START_CONFIRM : STOP_CONFIRM);
    if (!ok) return;
    setBusy(action);
    try {
      const next = action === "start" ? await api.gpu.start() : await api.gpu.stop();
      if (!next || typeof next.configured !== "boolean") {
        throw new Error("Некорректный ответ /api/gpu");
      }
      setGpu(next);
      setLoadError("");
      push(action === "start" ? "Группа Salad запускается" : "Группа Salad останавливается", "success");
    } catch (err) {
      push(formatApiError(err), "error");
      await reload();
    } finally {
      setBusy(null);
    }
  }

  const startEnabled = canStart(gpu) && !busy;
  const stopEnabled = canStop(gpu) && !busy;
  const pulse = gpu.status === "running" || gpu.status === "deploying" || gpu.status === "pending";

  return (
    <section className="card space-y-3 p-4" aria-labelledby="gpu-heading">
      <h2 id="gpu-heading" className="text-lg font-semibold text-slate-100">
        GPU Salad
      </h2>
      <p className="text-sm leading-relaxed text-slate-400">
        Start/Stop контейнерной группы из панели, без кабинета Salad. Это не тумблер воркера в
        шапке. Пока Running — идут GPU-часы. Не пользуешься — Stop. Start после Stop снова качает
        образ.
        {gpu.configured && (gpu.idle_stop_minutes ?? 0) > 0
          ? ` Авто-Stop через ${gpu.idle_stop_minutes} мин простоя (чат или local-рендер).`
          : ""}
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <span
          className={clsx(
            "h-2.5 w-2.5 shrink-0 rounded-full",
            gpu.billing ? "bg-amber-400 animate-pulse" : pulse ? "bg-sky-400 animate-pulse" : "bg-slate-500"
          )}
        />
        <div className="min-w-[12rem] flex-1">
          <div className="text-sm text-slate-100">{statusLabel(gpu)}</div>
          <div className="text-xs text-slate-500">
            {gpu.configured
              ? `Инстансы: running ${gpu.running_count}, creating ${gpu.creating_count}, allocating ${gpu.allocating_count}, stopping ${gpu.stopping_count}. Чат ${gpu.chat_ok ? "отвечает" : "не отвечает"}.`
              : "Ключ и имена группы задаются в .env на админ-VPS."}
          </div>
        </div>
        <button
          type="button"
          className="btn-primary"
          disabled={!startEnabled}
          onClick={() => void run("start")}
        >
          <Play size={14} />
          {busy === "start" ? "Запускаем…" : "Start"}
        </button>
        <button
          type="button"
          className="btn-ghost"
          disabled={!stopEnabled}
          onClick={() => void run("stop")}
        >
          <Square size={14} />
          {busy === "stop" ? "Останавливаем…" : "Stop"}
        </button>
      </div>
      {loadError ? <p className="text-sm text-rose-300">{loadError}</p> : null}
    </section>
  );
}
