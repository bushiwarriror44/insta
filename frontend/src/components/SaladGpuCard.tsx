import { useCallback, useState } from "react";
import { Play, Square } from "lucide-react";
import clsx from "clsx";

import { api, formatApiError } from "../api/client";
import type { GpuOut } from "../api/types";
import { useToast } from "../context/ToastContext";
import { usePollWhenVisible } from "../hooks/usePollWhenVisible";
import { canStart, canStop, chatLine, statusLabel } from "../lib/gpuLabels";
import { GpuConfirm } from "./GpuConfirm";

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
  wan_ok: null,
  detail: "",
};

export function SaladGpuCard() {
  const { push } = useToast();
  const [gpu, setGpu] = useState<GpuOut>(IDLE);
  const [busy, setBusy] = useState<"start" | "stop" | null>(null);
  const [ask, setAsk] = useState<"start" | "stop" | null>(null);
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

  async function confirm() {
    if (!ask || busy) return;
    const action = ask;
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
      setAsk(null);
    }
  }

  const startEnabled = canStart(gpu) && !busy;
  const stopEnabled = canStop(gpu) && !busy;
  const pulse =
    !loadError &&
    (gpu.status === "running" || gpu.status === "deploying" || gpu.status === "pending");

  return (
    <section className="card space-y-4 p-5" aria-labelledby="gpu-heading">
      <h2 id="gpu-heading" className="text-lg font-semibold text-slate-100">
        GPU Salad
      </h2>
      <p className="text-sm leading-relaxed text-slate-400">
        Запуск и остановка контейнерной группы из панели, без кабинета Salad. Это не тумблер воркера в
        шапке. Пока группа работает — идут GPU-часы. Не пользуешься — останови. Запуск после остановки снова качает
        образ.
        {gpu.configured && (gpu.idle_stop_minutes ?? 0) > 0
          ? ` Авто-стоп через ${gpu.idle_stop_minutes} мин простоя (чат или local-рендер).`
          : ""}
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <span
          className={clsx(
            "h-2.5 w-2.5 shrink-0 rounded-full",
            loadError
              ? "bg-rose-400"
              : gpu.billing
                ? "bg-amber-400 animate-pulse"
                : pulse
                  ? "bg-sky-400 animate-pulse"
                  : "bg-slate-500"
          )}
        />
        <div className="min-w-[12rem] flex-1">
          <div className="text-sm text-slate-100">{statusLabel(gpu)}</div>
          <div className="text-xs text-slate-500">
            {loadError
              ? "статус не обновился"
              : gpu.configured
                ? `Инстансы: работают ${gpu.running_count}, создаются ${gpu.creating_count}, выделяются ${gpu.allocating_count}, останавливаются ${gpu.stopping_count}. Чат ${chatLine(gpu)}.`
                : "Ключ и имена группы задаются в .env на админ-VPS."}
          </div>
        </div>
        <button
          type="button"
          className="btn-primary"
          disabled={!startEnabled}
          onClick={() => setAsk("start")}
        >
          <Play size={14} />
          {busy === "start" ? "Запускаем…" : "Запустить"}
        </button>
        <button
          type="button"
          className="btn-ghost"
          disabled={!stopEnabled}
          onClick={() => setAsk("stop")}
        >
          <Square size={14} />
          {busy === "stop" ? "Останавливаем…" : "Остановить"}
        </button>
      </div>
      {loadError ? <p className="text-sm text-rose-300">{loadError}</p> : null}
      <GpuConfirm action={ask} busy={Boolean(busy)} onNo={() => setAsk(null)} onYes={() => void confirm()} />
    </section>
  );
}
