import { ClipboardList, Copy, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { api, API_BASE, formatApiError } from "../api/client";
import type { AgentReportOut, AgentRunLogGroup } from "../api/types";
import { Card } from "../components/Card";
import { copyTextToClipboard } from "../components/DiagnosticLogPanel";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { PageShell } from "../components/PageShell";
import { useConfirm } from "../context/ConfirmContext";
import { useToast } from "../context/ToastContext";

function shotSrc(url: string) {
  if (url.startsWith("http") || url.startsWith(API_BASE)) return url;
  return `${API_BASE}${url}`;
}

function statusLabel(status: string) {
  if (status === "failed") return "ошибка";
  if (status === "needs_user") return "ждёт человека";
  if (status === "stopped") return "остановлено";
  return "готово";
}

export function Reports() {
  const { push } = useToast();
  const confirm = useConfirm();
  const [tab, setTab] = useState<"reports" | "logs">("reports");
  const [rows, setRows] = useState<AgentReportOut[]>([]);
  const [logs, setLogs] = useState<AgentRunLogGroup[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    setError(null);
    const [list, groups] = await Promise.all([api.agentReports.list(), api.agentReports.logs()]);
    setRows(list);
    setLogs(groups);
  }, []);

  useEffect(() => {
    void reload()
      .catch((err) => setError(formatApiError(err)))
      .finally(() => setLoading(false));
  }, [reload]);

  async function remove(row: AgentReportOut) {
    const ok = await confirm({
      title: "Удалить отчёт?",
      body: "Задача и её скриншоты будут удалены.",
      confirmLabel: "Удалить",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.agentReports.remove(row.id);
      setRows((current) => current.filter((item) => item.id !== row.id));
      push("Отчёт удалён", "success");
    } catch (err) {
      push(formatApiError(err), "error");
    }
  }

  async function copyLog(group: AgentRunLogGroup) {
    const ok = await copyTextToClipboard(group.text);
    push(ok ? "Лог скопирован" : "Не удалось скопировать", ok ? "success" : "error");
  }

  return (
    <PageShell error={error} onRetry={() => void reload().catch((err) => setError(formatApiError(err)))}>
      <PageHeader
        icon={ClipboardList}
        title="Отчёты"
        description="Задачи агента и подробный журнал каждого прогона."
      />
      <div className="mb-4 flex gap-2">
        <button
          type="button"
          className={tab === "reports" ? "btn-primary" : "btn-ghost"}
          onClick={() => setTab("reports")}
        >
          Отчёты
        </button>
        <button
          type="button"
          className={tab === "logs" ? "btn-primary" : "btn-ghost"}
          data-testid="run-logs-tab"
          onClick={() => setTab("logs")}
        >
          Логи выполнения
        </button>
      </div>
      {loading ? null : tab === "logs" ? (
        logs.length === 0 ? (
          <EmptyState title="Логов пока нет">
            Когда агент выполнит задачу, здесь появится журнал его действий.
          </EmptyState>
        ) : (
          <div className="space-y-4">
            {logs.map((group) => (
              <Card key={group.job_id} className="space-y-3 p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 space-y-1">
                    <div className="text-xs text-slate-500">
                      {statusLabel(group.status)} · {new Date(group.created_at).toLocaleString()}
                    </div>
                    <p className="text-sm text-slate-100">{group.prompt}</p>
                  </div>
                  <button
                    type="button"
                    className="btn-ghost text-sm"
                    data-testid="run-log-copy"
                    onClick={() => void copyLog(group)}
                  >
                    <Copy size={14} />
                    Копировать
                  </button>
                </div>
                <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-md bg-slate-950 p-3 text-xs text-slate-300">
                  {group.text}
                </pre>
              </Card>
            ))}
          </div>
        )
      ) : rows.length === 0 ? (
        <EmptyState title="Отчётов пока нет">
          Когда агент закончит задачу в чате или в Telegram, она появится здесь.
        </EmptyState>
      ) : (
        <div className="space-y-4">
          {rows.map((row) => (
            <Card key={row.id} className="space-y-3 p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 space-y-1">
                  <div className="text-xs text-slate-500">
                    {row.source === "telegram" ? "Telegram" : "Панель"} · {statusLabel(row.status)} ·{" "}
                    {new Date(row.created_at).toLocaleString()}
                  </div>
                  <p className="text-sm text-slate-100">{row.prompt}</p>
                </div>
                <button type="button" className="btn-ghost text-sm" onClick={() => void remove(row)}>
                  <Trash2 size={14} />
                  Удалить
                </button>
              </div>
              {row.error ? <p className="text-sm text-rose-200">{row.error}</p> : null}
              {row.reply ? <p className="whitespace-pre-wrap text-sm text-slate-300">{row.reply}</p> : null}
              {row.screenshots.length ? (
                <div className="flex flex-wrap gap-3">
                  {row.screenshots.map((url) => (
                    <a key={url} href={shotSrc(url)} target="_blank" rel="noreferrer">
                      <img
                        src={shotSrc(url)}
                        alt="Снимок отчёта"
                        className="max-h-64 rounded-md border border-slate-700"
                      />
                    </a>
                  ))}
                </div>
              ) : null}
            </Card>
          ))}
        </div>
      )}
    </PageShell>
  );
}
