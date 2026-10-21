import type { GpuOut } from "../api/types";

export function GpuConnectBar({
  gpu,
  includeReady = false,
}: {
  gpu: GpuOut | null;
  includeReady?: boolean;
}) {
  const phase = gpu?.connect_phase ?? "idle";
  if (!gpu || phase === "idle" || (phase === "ready" && !includeReady)) return null;
  const ratio = Math.min(1, Math.max(0, gpu.connect_ratio ?? 0));
  const percent = Math.round(ratio * 100);
  return (
    <div className="space-y-2 rounded-lg border border-slate-800 bg-slate-900/70 p-3" role="status">
      <p className="text-sm text-slate-200">{gpu.connect_label}</p>
      {gpu.connect_detail ? <p className="text-xs text-slate-500">{gpu.connect_detail}</p> : null}
      <div
        className="h-1.5 overflow-hidden rounded-full bg-slate-800"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        aria-label={gpu.connect_label || "Подключение к Salad"}
      >
        <div
          className="h-full rounded-full bg-sky-400 transition-[width] duration-500"
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
}
