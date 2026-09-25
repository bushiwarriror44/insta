import { useCallback, useState } from "react";
import { Clapperboard, Cpu, MessageSquare } from "lucide-react";
import clsx from "clsx";

import { api, formatApiError } from "../api/client";
import type { GpuOut } from "../api/types";
import { useToast } from "../context/ToastContext";
import { usePollWhenVisible } from "../hooks/usePollWhenVisible";
import { canStart, canStop, chatLine, statusLabel, wanLine } from "../lib/gpuLabels";
import { GpuConfirm } from "./GpuConfirm";

const POLL_MS = 8000;
const OPEN_POLL_MS = 2000;

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

export function ConnectionMenu() {
  const { push } = useToast();
  const [open, setOpen] = useState(false);
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

  usePollWhenVisible(reload, open ? OPEN_POLL_MS : POLL_MS);

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

  const live = !loadError && gpu.status === "running" && gpu.chat_ok;
  const startEnabled = canStart(gpu) && !busy;
  const stopEnabled = canStop(gpu) && !busy;

  return (
    <div className="relative">
      <button
        type="button"
        className="btn-ghost flex items-center gap-2 text-xs py-1 px-2"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span
          className={clsx("h-2 w-2 rounded-full", live ? "bg-emerald-400" : "bg-slate-500")}
          aria-hidden
        />
        Подключение
      </button>
      {open ? (
        <div className="absolute right-0 top-full z-20 mt-2 w-72 rounded-xl border border-slate-700 bg-slate-950 p-3 shadow-xl">
          <ul className="space-y-3 text-sm">
            <li className="flex items-start gap-2">
              <Cpu className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
              <span>
                <span className="block text-slate-200">Видеокарта</span>
                <span className="block text-xs text-slate-500">{statusLabel(gpu)}</span>
              </span>
            </li>
            <li className="flex items-start gap-2">
              <MessageSquare className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
              <span>
                <span className="block text-slate-200">Ollama</span>
                <span className="block text-xs text-slate-500">{chatLine(gpu)}</span>
              </span>
            </li>
            <li className="flex items-start gap-2">
              <Clapperboard className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
              <span>
                <span className="block text-slate-200">Wan</span>
                <span className="block text-xs text-slate-500">{wanLine(gpu)}</span>
              </span>
            </li>
          </ul>
          {loadError ? (
            <p className="mt-2 text-xs text-rose-300">статус не обновился: {loadError}</p>
          ) : null}
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              className="btn-primary flex-1 text-xs"
              disabled={!startEnabled}
              onClick={() => setAsk("start")}
            >
              Запустить
            </button>
            <button
              type="button"
              className="btn-ghost flex-1 text-xs"
              disabled={!stopEnabled}
              onClick={() => setAsk("stop")}
            >
              Остановить
            </button>
          </div>
        </div>
      ) : null}
      <GpuConfirm action={ask} busy={Boolean(busy)} onNo={() => setAsk(null)} onYes={() => void confirm()} />
    </div>
  );
}
