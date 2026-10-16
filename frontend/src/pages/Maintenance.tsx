import { Archive, RotateCcw, Save, Wrench } from "lucide-react";
import { useEffect, useState } from "react";

import { api, formatApiError } from "../api/client";
import { Card } from "../components/Card";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import type { BackupOut, RuntimeOut } from "../api/types";

const MIN_CONTEXT = 4096;
const MAX_CONTEXT = 40960;

function applyContext(rt: RuntimeOut, current: number) {
  return rt.context != null ? rt.context : current;
}

export function Maintenance() {
  const { role } = useAuth();
  const { push } = useToast();
  const [runtime, setRuntime] = useState<RuntimeOut | null>(null);
  const [backups, setBackups] = useState<BackupOut[]>([]);
  const [context, setContext] = useState(8192);
  const [busy, setBusy] = useState(false);
  const [restoringName, setRestoringName] = useState<string | null>(null);
  const contextOk = Number.isFinite(context) && context >= MIN_CONTEXT && context <= MAX_CONTEXT;
  const canRestore = role === "owner";

  async function reload() {
    const [rt, list] = await Promise.all([api.maintenance.runtime(), api.maintenance.backups()]);
    setRuntime(rt);
    setBackups(list);
    setContext((current) => applyContext(rt, current));
  }

  useEffect(() => {
    void reload().catch((err) => push(formatApiError(err), "error"));
  }, []);

  async function onRestore(row: BackupOut) {
    if (!canRestore) return;
    if (
      !window.confirm(
        `Восстановить базу из «${row.name}»? Текущая база будет заменена. Перезапустите API/worker после восстановления.`
      )
    ) {
      return;
    }
    setRestoringName(row.name);
    setBusy(true);
    try {
      await api.maintenance.restoreBackup(row.name);
      push("База восстановлена — перезапустите сервисы", "success");
      await reload();
    } catch (err) {
      push(formatApiError(err), "error");
    } finally {
      setRestoringName(null);
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader icon={Wrench} title="Обслуживание" />
      <Card>
        <h2 className="font-medium">Ollama</h2>
        {runtime ? (
          <>
            <div className="text-sm text-slate-400">
              {runtime.reachable ? `доступна · ${runtime.base_url}` : runtime.detail || "недоступна"}
            </div>
            <div className="text-sm">Модель: {runtime.model}</div>
            <div className="text-sm">
              Загружено: {runtime.loaded.map((m) => `${m.name} (${m.context})`).join(", ") || "—"}
            </div>
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
                <Save className="h-4 w-4" />
                Применить
              </button>
            </div>
          </>
        ) : (
          <div className="text-sm text-slate-500">Загрузка…</div>
        )}
      </Card>
      <Card>
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
                push("Копия снята", "success");
                await reload();
              } catch (err) {
                push(formatApiError(err), "error");
              } finally {
                setBusy(false);
              }
            }}
          >
            <Archive className="h-4 w-4" />
            Снять копию
          </button>
        </div>
        {backups.length === 0 ? <EmptyState>пока пусто</EmptyState> : null}
        <ul className="text-sm space-y-2">
          {backups.map((b) => (
            <li
              key={b.name}
              className="flex flex-wrap items-center justify-between gap-2 text-slate-400"
            >
              <span>
                {b.name} · {(b.bytes / 1024).toFixed(1)} КБ · {b.taken_at}
              </span>
              {canRestore ? (
                <button
                  type="button"
                  className="btn-ghost btn-compact"
                  disabled={busy || restoringName === b.name}
                  aria-label={`Восстановить ${b.name}`}
                  onClick={() => void onRestore(b)}
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                  Восстановить
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
