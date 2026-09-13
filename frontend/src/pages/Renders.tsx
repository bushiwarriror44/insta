import { Ban, Clapperboard, Layers, Play, RefreshCw } from "lucide-react";
import { useCallback, useState } from "react";
import clsx from "clsx";

import { api, formatApiError } from "../api/client";
import { Card } from "../components/Card";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { useToast } from "../context/ToastContext";
import { usePollWhenVisible } from "../hooks/usePollWhenVisible";
import { useAssistantMutate } from "../lib/assistantMutate";
import type { AccountOut, RenderBackendOut } from "../api/types";

type Gen = {
  id: number;
  status: string;
  prompt: string;
  stage: string;
  post_title: string;
  last_error: string | null;
  cost_usd: number;
  backend?: string;
};
type Join = { id: number; status: string; post_title: string; last_error: string | null; clips: number };

function backendLabel(name: string) {
  return name === "auto" ? "Авто" : name;
}

export function Renders() {
  const { push } = useToast();
  const [gens, setGens] = useState<Gen[]>([]);
  const [joins, setJoins] = useState<Join[]>([]);
  const [accounts, setAccounts] = useState<AccountOut[]>([]);
  const [backends, setBackends] = useState<RenderBackendOut[]>([]);
  const [prompt, setPrompt] = useState("");
  const [backend, setBackend] = useState("auto");
  const [accountId, setAccountId] = useState<number | "">("");
  const [joinIds, setJoinIds] = useState("");

  const reload = useCallback(async () => {
    const [g, c, accs, engines] = await Promise.all([
      api.factory.generations(),
      api.factory.compositions(),
      api.accounts.list(),
      api.factory.backends(),
    ]);
    setGens(g);
    setJoins(c);
    setAccounts(accs);
    setBackends(engines);
  }, []);

  const runAction = useCallback(
    async (fn: () => Promise<unknown>) => {
      try {
        await fn();
        await reload();
      } catch (err) {
        push(formatApiError(err), "error");
      }
    },
    [push, reload]
  );

  useAssistantMutate(() => reload().catch(() => undefined));

  const poll = useCallback(
    () => reload().catch((err) => push(formatApiError(err), "error")),
    [push, reload]
  );
  usePollWhenVisible(poll, 8000);

  return (
    <div className="space-y-6">
      <PageHeader icon={Clapperboard} title="Рендеры и склейки" />
      <Card className="p-4 space-y-3">
        <h2 className="font-medium">Новый рендер</h2>
        {backends.length ? (
          <div className="flex flex-wrap gap-2 text-sm">
            {backends.map((engine) => (
              <button
                key={engine.name}
                type="button"
                title={engine.detail || engine.licence}
                aria-pressed={backend === engine.name}
                onClick={() => setBackend(engine.name)}
                className={clsx(
                  "rounded-full px-2.5 py-1 text-xs ring-1 transition-colors",
                  backend === engine.name
                    ? "bg-brand-600/20 text-brand-200 ring-brand-500/40"
                    : engine.healthy
                      ? "text-emerald-400 ring-emerald-500/30 hover:bg-emerald-500/10"
                      : "text-slate-500 ring-slate-700 hover:bg-slate-800/60"
                )}
              >
                {backendLabel(engine.name)}
                {engine.experimental ? " · exp" : ""}
                {engine.healthy ? " · ок" : " · нет"}
              </button>
            ))}
          </div>
        ) : null}
        <textarea className="input min-h-[80px]" placeholder="Промпт" value={prompt} onChange={(e) => setPrompt(e.target.value)} />
        <select
          className="input"
          aria-label="бэкенд"
          value={backend}
          onChange={(e) => setBackend(e.target.value)}
        >
          {(backends.length ? backends : [{ name: "auto", healthy: true }]).map((engine) => (
            <option key={engine.name} value={engine.name}>
              {backendLabel(engine.name)}
              {engine.healthy === false ? " (нет)" : ""}
            </option>
          ))}
        </select>
        <select
          className="input"
          aria-label="аккаунт"
          value={accountId}
          onChange={(e) => setAccountId(e.target.value ? Number(e.target.value) : "")}
        >
          <option value="">без аккаунта</option>
          {accounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.username}
            </option>
          ))}
        </select>
        <button
          className="btn-primary"
          disabled={!prompt.trim()}
          onClick={async () => {
            try {
              await api.factory.createGeneration({
                prompt: prompt.trim(),
                backend,
                account_id: typeof accountId === "number" ? accountId : undefined,
              });
              setPrompt("");
              push("Рендер в очереди", "success", { label: "Открыть", href: "/renders" });
              await reload();
            } catch (err) {
              push(formatApiError(err), "error");
            }
          }}
        >
          <Play className="h-4 w-4" />
          Поставить рендер
        </button>
      </Card>
      <Card className="p-4">
        <h2 className="font-medium mb-3">Рендеры</h2>
        <table className="table-base">
          <thead>
            <tr>
              <th>ID</th>
              <th>Статус</th>
              <th>Бэкенд</th>
              <th>Заголовок</th>
              <th>Стадия</th>
              <th>$</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {gens.length === 0 ? (
              <tr>
                <td colSpan={7}>
                  <EmptyState>пока пусто</EmptyState>
                </td>
              </tr>
            ) : null}
            {gens.map((g) => (
              <tr key={g.id}>
                <td className="tabular-nums">{g.id}</td>
                <td>
                  <StatusBadge value={g.status} />
                </td>
                <td>{g.backend || "—"}</td>
                <td className="truncate" title={g.post_title || g.prompt}>
                  {g.post_title || g.prompt.slice(0, 60)}
                </td>
                <td className="truncate">{g.stage}</td>
                <td className="tabular-nums">{g.cost_usd}</td>
                <td className="text-right">
                  <div className="flex justify-end gap-1 flex-wrap">
                    {g.status === "queued" ? (
                      <button
                        className="btn-ghost btn-compact"
                        aria-label="Отменить"
                        onClick={() => void runAction(() => api.factory.cancelGeneration(g.id))}
                      >
                        <Ban className="h-4 w-4" />
                        Отменить
                      </button>
                    ) : null}
                    {["failed", "dead", "cancelled"].includes(g.status) ? (
                      <button
                        className="btn-ghost btn-compact"
                        onClick={() => void runAction(() => api.factory.retryGeneration(g.id))}
                      >
                        <RefreshCw className="h-4 w-4" />
                        Повторить
                      </button>
                    ) : null}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <Card className="p-4 space-y-3">
        <h2 className="font-medium">Склейки</h2>
        <div className="flex gap-2">
          <input className="input" placeholder="id клипов через запятую" value={joinIds} onChange={(e) => setJoinIds(e.target.value)} />
          <button
            className="btn-ghost shrink-0"
            onClick={async () => {
              const clip_ids = joinIds.split(",").map((s) => Number(s.trim())).filter(Boolean);
              if (clip_ids.length < 2) {
                push("Нужны минимум два id клипов через запятую", "error");
                return;
              }
              try {
                await api.factory.createComposition({ clip_ids, account_id: typeof accountId === "number" ? accountId : undefined });
                setJoinIds("");
                push("Склейка в очереди", "success", { label: "Открыть", href: "/renders" });
                await reload();
              } catch (err) {
                push(formatApiError(err), "error");
              }
            }}
          >
            <Layers className="h-4 w-4" />
            Склеить
          </button>
        </div>
        <table className="table-base">
          <thead>
            <tr>
              <th>ID</th>
              <th>Статус</th>
              <th>Пост</th>
              <th>Клипов</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {joins.length === 0 ? (
              <tr>
                <td colSpan={5}>
                  <EmptyState>пока пусто</EmptyState>
                </td>
              </tr>
            ) : null}
            {joins.map((j) => (
              <tr key={j.id}>
                <td className="tabular-nums">{j.id}</td>
                <td>
                  <StatusBadge value={j.status} />
                </td>
                <td className="truncate" title={j.post_title}>
                  {j.post_title}
                </td>
                <td className="tabular-nums">{j.clips}</td>
                <td className="text-right">
                  <div className="flex justify-end gap-1 flex-wrap">
                    {j.status === "queued" ? (
                      <button
                        className="btn-ghost btn-compact"
                        aria-label="Отменить"
                        onClick={() => void runAction(() => api.factory.cancelComposition(j.id))}
                      >
                        <Ban className="h-4 w-4" />
                        Отменить
                      </button>
                    ) : null}
                    {["failed", "dead", "cancelled"].includes(j.status) ? (
                      <button
                        className="btn-ghost btn-compact"
                        onClick={() => void runAction(() => api.factory.retryComposition(j.id))}
                      >
                        <RefreshCw className="h-4 w-4" />
                        Повторить
                      </button>
                    ) : null}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
