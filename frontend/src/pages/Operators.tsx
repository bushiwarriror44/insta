import type { FormEvent } from "react";
import { useCallback, useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { Copy, KeyRound, Plus, ShieldOff } from "lucide-react";

import { api, formatApiError } from "../api/client";
import type { PanelOperatorCreatedOut, PanelOperatorOut } from "../api/types";
import { copyTextToClipboard } from "../components/DiagnosticLogPanel";
import { EmptyState } from "../components/EmptyState";
import { Modal } from "../components/Modal";
import { PageHeader } from "../components/PageHeader";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";

export function Operators() {
  const { role } = useAuth();
  const { push } = useToast();
  const [rows, setRows] = useState<PanelOperatorOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [label, setLabel] = useState("");
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState<PanelOperatorCreatedOut | null>(null);
  const [copied, setCopied] = useState(false);
  const [revokingId, setRevokingId] = useState<number | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      setRows(await api.operators.list());
    } catch (err) {
      push(formatApiError(err), "error");
    } finally {
      setLoading(false);
    }
  }, [push]);

  useEffect(() => {
    if (role === "owner") void reload();
  }, [role, reload]);

  if (role !== "owner") {
    return <Navigate to="/" replace />;
  }

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    const trimmed = label.trim();
    if (!trimmed) return;
    setCreating(true);
    try {
      const out = await api.operators.create(trimmed);
      setCreated(out);
      setLabel("");
      setCopied(false);
      await reload();
      push(`Оператор «${out.label}» создан`, "success");
    } catch (err) {
      push(formatApiError(err), "error");
    } finally {
      setCreating(false);
    }
  }

  async function onRevoke(row: PanelOperatorOut) {
    if (!row.active) return;
    if (!window.confirm(`Отозвать пароль оператора «${row.label}»?`)) return;
    setRevokingId(row.id);
    try {
      await api.operators.revoke(row.id);
      push(`Пароль «${row.label}» отозван`, "success");
      await reload();
    } catch (err) {
      push(formatApiError(err), "error");
    } finally {
      setRevokingId(null);
    }
  }

  async function copyPassword() {
    if (!created?.password) return;
    const ok = await copyTextToClipboard(created.password);
    setCopied(ok);
    push(ok ? "Пароль скопирован" : "Не удалось скопировать", ok ? "success" : "error");
  }

  return (
    <div className="space-y-6">
      <PageHeader
        icon={KeyRound}
        title="Доступы"
        description="Генерация и отзыв паролей операторов. Вкладка доступна только владельцу (мастер-пароль / ADMIN_TOKEN)."
      />

      <form onSubmit={onCreate} className="card p-4 flex flex-wrap items-end gap-3">
        <div className="flex-1 min-w-[200px]">
          <label className="label" htmlFor="operator-label">
            Метка оператора
          </label>
          <input
            id="operator-label"
            className="input"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="например: ivan"
            autoComplete="off"
          />
        </div>
        <button type="submit" className="btn-primary" disabled={creating || !label.trim()}>
          <Plus size={16} />
          {creating ? "Создание…" : "Сгенерировать пароль"}
        </button>
      </form>

      <div className="card overflow-hidden">
        <table className="table-base">
          <thead>
            <tr>
              <th>Метка</th>
              <th>Создан</th>
              <th>Статус</th>
              <th>Последний вход</th>
              <th className="text-right">Действия</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={5} className="px-2 py-8 text-center text-slate-500">
                  Загрузка…
                </td>
              </tr>
            ) : rows.length === 0 ? (
              <tr>
                <td colSpan={5}>
                  <EmptyState>Операторов пока нет</EmptyState>
                </td>
              </tr>
            ) : (
              rows.map((row) => (
                <tr key={row.id} className="hover:bg-slate-900/40">
                  <td className="font-medium truncate" title={row.label}>
                    {row.label}
                  </td>
                  <td className="text-slate-400 truncate" title={new Date(row.created_at).toLocaleString()}>
                    {new Date(row.created_at).toLocaleString()}
                  </td>
                  <td>
                    {row.active ? (
                      <span className="text-emerald-300">активен</span>
                    ) : (
                      <span className="text-slate-500">отозван</span>
                    )}
                  </td>
                  <td className="text-slate-400 truncate">
                    {row.last_used_at
                      ? new Date(row.last_used_at).toLocaleString()
                      : "—"}
                  </td>
                  <td className="text-right">
                    <button
                      type="button"
                      className="btn-ghost btn-compact"
                      aria-label="Отозвать"
                      disabled={!row.active || revokingId === row.id}
                      onClick={() => void onRevoke(row)}
                    >
                      <ShieldOff size={14} />
                      Отозвать
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <Modal
        open={created !== null}
        onClose={() => setCreated(null)}
        title="Пароль оператора"
        footer={
          <button type="button" className="btn-primary" onClick={() => setCreated(null)}>
            Закрыть
          </button>
        }
      >
        {created ? (
          <div className="space-y-3 text-sm">
            <p className="text-slate-300">
              Оператор <span className="font-medium text-white">{created.label}</span>.
              Скопируйте пароль сейчас — повторно он не показывается.
            </p>
            <div className="rounded-lg border border-slate-700 bg-slate-950/60 p-3 font-mono text-xs break-all">
              {created.password}
            </div>
            <button type="button" className="btn-ghost w-full" onClick={() => void copyPassword()}>
              <Copy size={14} />
              {copied ? "Скопировано" : "Копировать пароль"}
            </button>
            <p className="text-xs text-slate-500 flex items-start gap-2">
              <KeyRound size={14} className="mt-0.5 shrink-0" />
              Оператор входит этим паролем на странице логина (вместо ADMIN_TOKEN).
            </p>
          </div>
        ) : null}
      </Modal>
    </div>
  );
}
