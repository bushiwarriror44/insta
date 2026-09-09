import { useEffect, useState } from "react";

import { api, formatApiError } from "../api/client";
import { Card } from "../components/Card";
import { useToast } from "../context/ToastContext";
import type { BackupOut, RuntimeOut } from "../api/types";

const MIN_CONTEXT = 4096;
const MAX_CONTEXT = 40960;

function applyContext(rt: RuntimeOut, current: number) {
  return rt.context != null ? rt.context : current;
}

export function Maintenance() {
  const { push } = useToast();
  const [runtime, setRuntime] = useState<RuntimeOut | null>(null);
  const [backups, setBackups] = useState<BackupOut[]>([]);
  const [context, setContext] = useState(8192);
  const [busy, setBusy] = useState(false);
  const contextOk = Number.isFinite(context) && context >= MIN_CONTEXT && context <= MAX_CONTEXT;

  async function reload() {
    const [rt, list] = await Promise.all([api.maintenance.runtime(), api.maintenance.backups()]);
    setRuntime(rt);
    setBackups(list);
    setContext((current) => applyContext(rt, current));
  }

  useEffect(() => {
    void reload().catch((err) => push(formatApiError(err), "error"));
  }, []);

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Обслуживание</h1>
      <Card className="p-4 space-y-3">
        <h2 className="font-medium">Ollama</h2>
        {runtime ? (
          <>
            <div className="text-sm text-slate-400">
              {runtime.reachable ? `доступна · ${runtime.base_url}` : runtime.detail || "недоступна"}
            </div>
            <div className="text-sm">Модель: {runtime.model}</div>
            <div className="text-sm">Загружено: {runtime.loaded.map((m) => `${m.name} (${m.context})`).join(", ") || "—"}</div>
            <div className="flex gap-2 items-end">
              <label className="text-sm">
                Контекст
                <input
                  className="input mt-1"
                  type="number"
                  min={MIN_CONTEXT}
                  max={MAX_CONTEXT}
                  value={context}
                  onChange={(e) => setContext(Number(e.target.value))}
                />
              </label>
              <button
                type="button"
                className="btn-primary"
                disabled={busy || !runtime.reachable || !contextOk}
                onClick={async () => {
                  setBusy(true);
                  try {
                    const next = await api.maintenance.setContext(context);
                    setRuntime(next);
                    setContext((current) => applyContext(next, current));
                    push("Модель перезагружена", "success");
                  } catch (err) {
                    push(formatApiError(err), "error");
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Применить
              </button>
            </div>
          </>
        ) : (
          <div className="text-sm text-slate-500">Загрузка…</div>
        )}
      </Card>
      <Card className="p-4 space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="font-medium">Копии базы</h2>
          <button
            type="button"
            className="btn-primary"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                const created = await api.maintenance.takeBackup();
                setBackups((rows) => [created, ...rows.filter((b) => b.name !== created.name)]);
                push("Копия снята", "success", { label: "Открыть", href: "/maintenance" });
                await reload();
              } catch (err) {
                push(formatApiError(err), "error");
              } finally {
                setBusy(false);
              }
            }}
          >
            Снять копию
          </button>
        </div>
        <ul className="text-sm space-y-1">
          {backups.map((b) => (
            <li key={b.name} className="text-slate-400">
              {b.name} · {(b.bytes / 1024).toFixed(1)} КБ · {b.taken_at}
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
