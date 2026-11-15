import { Copy } from "lucide-react";
import { useEffect, useState } from "react";

import { api, formatApiError } from "../api/client";
import type { LlmGatewayCredentialsOut } from "../api/types";
import { copyTextToClipboard } from "./DiagnosticLogPanel";
import { useToast } from "../context/ToastContext";
import { ConfirmDialog } from "./ConfirmDialog";

type Layout = "admin" | "dock-api" | "dock-mcp";

type Props = {
  layout: Layout;
  onHide?: () => void;
};

function formatActivityAt(iso: string) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

export function LlmGatewayPanel({ layout, onHide }: Props) {
  const { push: toast } = useToast();
  const [gateway, setGateway] = useState<LlmGatewayCredentialsOut | null>(null);
  const [gatewayError, setGatewayError] = useState("");
  const [gatewayBusy, setGatewayBusy] = useState(false);
  const [copiedField, setCopiedField] = useState<string | null>(null);
  const [rotateConfirmOpen, setRotateConfirmOpen] = useState(false);

  const loadGateway = async (opts?: { rotate?: boolean; enabled?: boolean }) => {
    setGatewayBusy(true);
    setGatewayError("");
    try {
      let next: LlmGatewayCredentialsOut;
      if (typeof opts?.enabled === "boolean") {
        next = await api.llmGateway.setEnabled(opts.enabled);
      } else if (opts?.rotate) {
        next = await api.llmGateway.rotate();
      } else {
        next = await api.llmGateway.credentials();
      }
      setGateway(next);
    } catch (err) {
      setGatewayError(formatApiError(err));
    } finally {
      setGatewayBusy(false);
    }
  };

  useEffect(() => {
    void loadGateway();
  }, []);

  const copyField = async (field: string, value: string) => {
    const ok = await copyTextToClipboard(value);
    if (!ok) {
      toast("Не удалось скопировать", "error");
      return;
    }
    setCopiedField(field);
    window.setTimeout(() => setCopiedField((cur) => (cur === field ? null : cur)), 1500);
  };

  const showApiFields = layout === "admin" || layout === "dock-api";
  const showMcpJson = layout === "admin" || layout === "dock-mcp";

  const gatewayControls = gateway ? (
    <div className="space-y-3" data-testid="assistant-gateway-controls">
      <label className="flex items-center gap-2 text-sm text-slate-200">
        <input
          type="checkbox"
          className="rounded border-slate-600"
          checked={gateway.enabled}
          disabled={gatewayBusy}
          aria-label="Шлюз включён"
          data-testid={layout === "admin" ? "admin-gateway-enabled" : undefined}
          onChange={(e) => void loadGateway({ enabled: e.target.checked })}
        />
        Шлюз включён
      </label>
      <p className="text-xs text-slate-500">
        Модель: <span className="text-slate-300">{gateway.model}</span>
        {" · "}
        {!gateway.enabled ? (
          <span className="text-amber-400">выключен</span>
        ) : gateway.upstream_ok ? (
          <span className="text-emerald-400">шлюз доступен</span>
        ) : (
          <span className="text-amber-400">upstream не отвечает</span>
        )}
      </p>
      <div>
        <p className="mb-1 text-[11px] uppercase tracking-wide text-slate-500">
          Недавние подключения
        </p>
        {gateway.recent.length === 0 ? (
          <p className="text-xs text-slate-500" data-testid="assistant-gateway-recent-empty">
            Пока никто не подключался
          </p>
        ) : (
          <ul
            className="max-h-36 space-y-1 overflow-y-auto text-[11px] text-slate-400"
            data-testid="assistant-gateway-recent"
          >
            {gateway.recent.map((row, i) => (
              <li key={`${row.at}-${row.path}-${i}`} className="font-mono leading-relaxed">
                <span className="text-slate-500">{formatActivityAt(row.at)}</span>
                {" · "}
                <span className="text-slate-300">{row.channel}</span>
                {" · "}
                {row.method} {row.path}
                {row.client_ip ? ` · ${row.client_ip}` : ""}
                {" · "}
                <span className={row.status >= 400 ? "text-rose-300" : "text-emerald-400"}>
                  {row.status}
                </span>
                {row.detail ? (
                  <span className="block pl-0 text-slate-500 normal-case">{row.detail}</span>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  ) : null;

  return (
  <div className="space-y-3" data-testid={layout === "admin" ? "admin-connections-credentials" : undefined}>
      {gatewayError ? <p className="text-sm text-rose-300">{gatewayError}</p> : null}
      {gatewayBusy && !gateway ? (
        <p className="text-sm text-slate-400">Загружаю…</p>
      ) : gateway ? (
        <>
          {gatewayControls}
          {showApiFields ? (
            <div className="space-y-3">
              {layout === "admin" ? (
                <p className="text-sm font-medium text-slate-200">OpenAI-совместимый прокси</p>
              ) : null}
              <label className="block space-y-1">
                <span className="text-[11px] uppercase tracking-wide text-slate-500">Base URL</span>
                <div className="flex gap-2">
                  <input
                    className="input flex-1 font-mono text-xs"
                    readOnly
                    value={gateway.base_url}
                    aria-label="Base URL"
                  />
                  <button
                    type="button"
                    className="btn-ghost shrink-0 text-xs"
                    onClick={() => void copyField("base_url", gateway.base_url)}
                  >
                    <Copy className="mr-1 inline h-3.5 w-3.5" />
                    {copiedField === "base_url" ? "Скопировано" : "Копировать"}
                  </button>
                </div>
              </label>
              <label className="block space-y-1">
                <span className="text-[11px] uppercase tracking-wide text-slate-500">API Key</span>
                <div className="flex gap-2">
                  <input
                    className="input flex-1 font-mono text-xs"
                    readOnly
                    value={gateway.api_key}
                    aria-label="API Key"
                  />
                  <button
                    type="button"
                    className="btn-ghost shrink-0 text-xs"
                    onClick={() => void copyField("api_key", gateway.api_key)}
                  >
                    <Copy className="mr-1 inline h-3.5 w-3.5" />
                    {copiedField === "api_key" ? "Скопировано" : "Копировать"}
                  </button>
                </div>
              </label>
              {layout === "admin" ? (
                <label className="block space-y-1">
                  <span className="text-[11px] uppercase tracking-wide text-slate-500">MCP URL</span>
                  <div className="flex gap-2">
                    <input
                      className="input flex-1 font-mono text-xs"
                      readOnly
                      value={gateway.mcp_url}
                      aria-label="MCP URL"
                    />
                    <button
                      type="button"
                      className="btn-ghost shrink-0 text-xs"
                      onClick={() => void copyField("mcp_url", gateway.mcp_url)}
                    >
                      <Copy className="mr-1 inline h-3.5 w-3.5" />
                      {copiedField === "mcp_url" ? "Скопировано" : "Копировать"}
                    </button>
                  </div>
                </label>
              ) : null}
            </div>
          ) : null}
          {showMcpJson ? (
            <div className="space-y-2">
              {layout === "admin" ? (
                <p className="text-sm font-medium text-slate-200">Конфигурация MCP</p>
              ) : null}
              <textarea
                className="input min-h-[10rem] w-full resize-y font-mono text-[11px] leading-relaxed"
                readOnly
                value={gateway.mcp_json}
                aria-label="MCP JSON"
              />
            </div>
          ) : null}
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <button
              type="button"
              className="btn-ghost text-xs"
              disabled={gatewayBusy}
              onClick={() => setRotateConfirmOpen(true)}
            >
              {gatewayBusy ? "…" : "Перегенерировать ключ"}
            </button>
            <button
              type="button"
              className="btn-ghost text-xs"
              disabled={gatewayBusy}
              onClick={() => void loadGateway()}
            >
              Обновить
            </button>
            {onHide ? (
              <button
                type="button"
                className="ml-auto text-xs text-slate-500 hover:text-slate-300"
                onClick={onHide}
              >
                Скрыть
              </button>
            ) : null}
          </div>
        </>
      ) : null}
      <ConfirmDialog
        open={rotateConfirmOpen}
        title="Перегенерировать ключ?"
        body="Старые клиенты (Cursor и др.) сразу перестанут подключаться."
        confirmLabel="Перегенерировать"
        cancelLabel="Отмена"
        danger
        onConfirm={() => {
          setRotateConfirmOpen(false);
          void loadGateway({ rotate: true });
        }}
        onCancel={() => setRotateConfirmOpen(false)}
      />
    </div>
  );
}