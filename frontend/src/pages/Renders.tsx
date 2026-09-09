import { useCallback, useState } from "react";

import { api, formatApiError } from "../api/client";
import { Card } from "../components/Card";
import { StatusBadge } from "../components/StatusBadge";
import { useToast } from "../context/ToastContext";
import { usePollWhenVisible } from "../hooks/usePollWhenVisible";
import { useAssistantMutate } from "../lib/assistantMutate";
import type { AccountOut } from "../api/types";

type Gen = {
  id: number;
  status: string;
  prompt: string;
  stage: string;
  post_title: string;
  last_error: string | null;
  cost_usd: number;
};
type Join = { id: number; status: string; post_title: string; last_error: string | null; clips: number };

export function Renders() {
  const { push } = useToast();
  const [gens, setGens] = useState<Gen[]>([]);
  const [joins, setJoins] = useState<Join[]>([]);
  const [accounts, setAccounts] = useState<AccountOut[]>([]);
  const [prompt, setPrompt] = useState("");
  const [accountId, setAccountId] = useState<number | "">("");
  const [joinIds, setJoinIds] = useState("");

  const reload = useCallback(async () => {
    const [g, c, accs] = await Promise.all([
      api.factory.generations(),
      api.factory.compositions(),
      api.accounts.list(),
    ]);
    setGens(g);
    setJoins(c);
    setAccounts(accs);
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
      <h1 className="text-xl font-semibold">Рендеры и склейки</h1>
      <Card className="p-4 space-y-3">
        <h2 className="font-medium">Новый рендер</h2>
        <textarea className="input min-h-[80px]" placeholder="Промпт" value={prompt} onChange={(e) => setPrompt(e.target.value)} />
        <select className="input" value={accountId} onChange={(e) => setAccountId(e.target.value ? Number(e.target.value) : "")}>
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
          Поставить рендер
        </button>
      </Card>
      <Card className="p-4">
        <h2 className="font-medium mb-3">fal.ai</h2>
        <table className="table-base">
          <thead>
            <tr>
              <th>ID</th>
              <th>Статус</th>
              <th>Заголовок</th>
              <th>Стадия</th>
              <th>$</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {gens.map((g) => (
              <tr key={g.id} className="hover:bg-slate-900/40">
                <td className="tabular-nums">{g.id}</td>
                <td>
                  <StatusBadge value={g.status} />
                </td>
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
                        Отменить
                      </button>
                    ) : null}
                    {["failed", "dead", "cancelled"].includes(g.status) ? (
                      <button
                        className="btn-ghost btn-compact"
                        onClick={() => void runAction(() => api.factory.retryGeneration(g.id))}
                      >
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
            {joins.map((j) => (
              <tr key={j.id} className="hover:bg-slate-900/40">
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
                        Отменить
                      </button>
                    ) : null}
                    {["failed", "dead", "cancelled"].includes(j.status) ? (
                      <button
                        className="btn-ghost btn-compact"
                        onClick={() => void runAction(() => api.factory.retryComposition(j.id))}
                      >
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
