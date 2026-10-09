import { Clapperboard } from "lucide-react";
import { Link } from "react-router-dom";

import { StatusBadge } from "./StatusBadge";

export type ActiveGeneration = {
  id: number;
  status: string;
  stage: string;
  backend: string;
  assetId: number | null;
};

function parseDetail(detail: string): { backend?: string; stage?: string; assetId?: number } {
  const out: { backend?: string; stage?: string; assetId?: number } = {};
  for (const part of detail.split("|")) {
    const [key, ...rest] = part.split("=");
    const value = rest.join("=");
    if (key === "backend" && value) out.backend = value;
    if (key === "stage" && value) out.stage = value;
    if (key === "asset_id" && value) {
      const n = Number(value);
      if (!Number.isNaN(n)) out.assetId = n;
    }
  }
  return out;
}

export function generationFromStep(
  text: string,
  name: string,
  detail?: string
): ActiveGeneration | null {
  const id = Number(name);
  if (!Number.isFinite(id)) return null;
  const parsed = parseDetail(detail || "");
  return {
    id,
    status: text || "running",
    stage: parsed.stage || "",
    backend: parsed.backend || "",
    assetId: parsed.assetId ?? null,
  };
}

export function mergeGeneration(
  prev: ActiveGeneration | null,
  patch: Partial<ActiveGeneration> & { id: number }
): ActiveGeneration {
  const base = prev?.id === patch.id ? prev : null;
  return {
    id: patch.id,
    status: patch.status ?? base?.status ?? "running",
    stage: patch.stage ?? base?.stage ?? "",
    backend: patch.backend ?? base?.backend ?? "",
    assetId: patch.assetId !== undefined ? patch.assetId : base?.assetId ?? null,
  };
}

const TERMINAL = new Set(["done", "failed", "dead", "cancelled"]);

export function RenderProgressCard({ job }: { job: ActiveGeneration }) {
  const done = job.status === "done";
  const failed = ["failed", "dead"].includes(job.status);
  const stage = job.stage || (done ? "готово" : failed ? "ошибка" : "в очереди…");

  return (
    <div
      className="space-y-2 rounded-lg border border-brand-500/30 bg-slate-900/80 p-3"
      data-testid="render-progress-card"
      role="status"
    >
      <div className="flex flex-wrap items-center gap-2 text-sm text-slate-100">
        <Clapperboard className="h-4 w-4 shrink-0 text-brand-300" />
        <span className="font-medium">Рендер #{job.id}</span>
        <StatusBadge value={job.status} />
        {job.backend ? <span className="text-xs text-slate-500">{job.backend}</span> : null}
      </div>
      <p className="text-xs text-slate-400">{stage}</p>
      {!done && !failed ? (
        <div className="h-1.5 overflow-hidden rounded-full bg-slate-800">
          <div className="h-full w-1/3 animate-pulse rounded-full bg-sky-400" />
        </div>
      ) : null}
      {done && job.assetId ? (
        <p className="text-xs text-brand-300">
          Готово: клип #{job.assetId}.{" "}
          <Link to="/publishing" className="underline hover:text-brand-200">
            Открыть библиотеку
          </Link>
        </p>
      ) : null}
    </div>
  );
}

export function isTerminalGeneration(status: string): boolean {
  return TERMINAL.has(status);
}
