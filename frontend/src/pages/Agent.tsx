import { Ban, Calendar, CalendarDays, Eye, Plus, Send, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { api, formatApiError } from "../api/client";
import { AgentToggle } from "../components/AgentToggle";
import { Card } from "../components/Card";
import { EmptyState } from "../components/EmptyState";
import { Loader } from "../components/Loader";
import { Modal } from "../components/Modal";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { useToast } from "../context/ToastContext";
import { AGENT_PAGE_MANUAL, agentWorkHint } from "../lib/agentManual";
import { useAssistantMutate } from "../lib/assistantMutate";
import { refreshNavBadges } from "../lib/uiEvents";
import type { AccountOut } from "../api/types";

type SourceRow = { id: number; kind: string; value: string; label: string; enabled: boolean; last_status: string };
type QuestionRow = { id: number; question: string; why: string; assumed: string; open: boolean };
type PlanRow = {
  id: number;
  status: string;
  count: number;
  planned: number;
  spread_over_days: number | null;
  last_error: string | null;
  created_at: string | null;
};
type RunRow = {
  id: number;
  account_username: string | null;
  ok: boolean;
  model: string;
  requested: number;
  returned: number;
  cost_usd: number;
  error: string | null;
  created_at: string;
};

export function Agent() {
  const { push } = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const accountFromUrl = Number(searchParams.get("account") || searchParams.get("id") || 0) || null;
  const [accounts, setAccounts] = useState<AccountOut[]>([]);
  const [accountId, setAccountIdState] = useState<number | "">(accountFromUrl ?? "");
  const [brief, setBrief] = useState("");
  const [count, setCount] = useState(5);
  const [duration, setDuration] = useState(5);
  const [autoSchedule, setAutoSchedule] = useState(true);
  const [presets, setPresets] = useState<Array<{ id: number; name: string; brief: string }>>([]);
  const [sourceValue, setSourceValue] = useState("");
  const [sources, setSources] = useState<SourceRow[]>([]);
  const [questions, setQuestions] = useState<QuestionRow[]>([]);
  const [plans, setPlans] = useState<PlanRow[]>([]);
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [runs, setRuns] = useState<RunRow[]>([]);
  const [runDetail, setRunDetail] = useState<{
    id: number;
    prompt: string;
    ideas: unknown;
    questions: unknown;
    sources: unknown;
    cost_usd: number;
    error: string | null;
  } | null>(null);
  const [busy, setBusy] = useState(false);

  const selectedId = typeof accountId === "number" ? accountId : null;

  const setAccountId = (next: number | "") => {
    setAccountIdState(next);
    setSearchParams(
      (prev) => {
        const params = new URLSearchParams(prev);
        if (typeof next === "number") params.set("account", String(next));
        else {
          params.delete("account");
          params.delete("id");
        }
        return params;
      },
      { replace: true }
    );
  };

  async function reload() {
    const [accs, list, presetList] = await Promise.all([
      api.accounts.list(),
      api.factory.agentRuns(),
      api.factory.presets().catch(() => []),
    ]);
    setAccounts(accs);
    setRuns(list);
    setPresets(presetList);
    const fromUrl =
      accountFromUrl && accs.some((a) => a.id === accountFromUrl) ? accountFromUrl : null;
    const nextId =
      fromUrl ??
      (selectedId && accs.some((a) => a.id === selectedId) ? selectedId : accs[0]?.id);
    if (nextId) {
      setAccountIdState(nextId);
      if (!searchParams.get("account") && !searchParams.get("id")) {
        setSearchParams(
          (prev) => {
            const params = new URLSearchParams(prev);
            params.set("account", String(nextId));
            return params;
          },
          { replace: true }
        );
      }
      const acc = accs.find((a) => a.id === nextId);
      setBrief(acc?.brief || "");
      const [src, qs, planRows] = await Promise.all([
        api.factory.sources(nextId),
        api.factory.questions(nextId),
        api.factory.plans(nextId).catch(() => []),
      ]);
      setSources(src);
      setQuestions(qs);
      setPlans(planRows);
    }
  }

  useAssistantMutate(() => reload().catch((err) => push(formatApiError(err), "error")));

  useEffect(() => {
    void reload().catch((err) => push(formatApiError(err), "error"));
  }, []);

  useEffect(() => {
    if (accountFromUrl && accountFromUrl !== accountId) {
      setAccountIdState(accountFromUrl);
    }
  }, [accountFromUrl]);

  useEffect(() => {
    if (!selectedId) return;
    const acc = accounts.find((a) => a.id === selectedId);
    if (acc) setBrief(acc.brief || "");
    void Promise.all([
      api.factory.sources(selectedId),
      api.factory.questions(selectedId),
      api.factory.plans(selectedId).catch(() => []),
    ])
      .then(([src, qs, planRows]) => {
        setSources(src);
        setQuestions(qs);
        setPlans(planRows);
      })
      .catch((err) => push(formatApiError(err), "error"));
  }, [selectedId]);

  return (
    <div className="space-y-6">
      <PageHeader
        icon={Sparkles}
        title="Контент-агент"
        description="План роликов (PlanJob). Нижний чат и тумблер воркера — другие процессы."
      />
      <p
        role="status"
        data-testid="agent-work-hint"
        className="rounded-lg border border-slate-800 bg-slate-950/50 px-3 py-2 text-sm text-slate-400"
      >
        {agentWorkHint({
          accounts: accounts.length,
          brief,
          questions: questions.length,
          busy,
          autoSchedule,
        })}
      </p>
      <section className="card space-y-2 p-4" aria-labelledby="agent-manual-heading">
        <h2 id="agent-manual-heading" className="text-lg font-semibold text-slate-100">
          Мануал
        </h2>
        {AGENT_PAGE_MANUAL.map((section) => (
          <details key={section.id} open className="rounded-lg border border-slate-800 bg-slate-950/50 px-3 py-2">
            <summary className="cursor-pointer text-sm font-medium text-slate-200">{section.title}</summary>
            <div className="mt-2 space-y-2 text-sm leading-relaxed text-slate-400">
              {section.body.map((paragraph) => (
                <p key={paragraph}>{paragraph}</p>
              ))}
            </div>
          </details>
        ))}
      </section>
      <Card className="p-4">
        <h2 className="font-medium mb-3">Процесс агента</h2>
        <AgentToggle />
      </Card>
      <Card className="p-4 space-y-3">
        <label className="text-sm">
          Аккаунт
          <select
            className="input mt-1"
            aria-label="Аккаунт агента"
            value={accountId}
            onChange={(e) => setAccountId(e.target.value ? Number(e.target.value) : "")}
          >
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.username} ({a.platform || "instagram"})
              </option>
            ))}
          </select>
        </label>
        {presets.length > 0 ? (
          <label className="text-sm block">
            Пресет
            <select
              className="input mt-1"
              defaultValue=""
              onChange={(e) => {
                const preset = presets.find((p) => String(p.id) === e.target.value);
                if (preset) setBrief(preset.brief);
              }}
            >
              <option value="">—</option>
              {presets.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <label className="text-sm block">
          Бриф
          <textarea className="input mt-1 min-h-[120px]" value={brief} onChange={(e) => setBrief(e.target.value)} />
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label className="text-sm">
            Сколько роликов
            <input className="input mt-1" type="number" min={1} max={20} value={count} onChange={(e) => setCount(Number(e.target.value))} />
          </label>
          <label className="text-sm">
            Длительность, с
            <input className="input mt-1" type="number" min={5} max={10} value={duration} onChange={(e) => setDuration(Number(e.target.value))} />
          </label>
        </div>
        <label className="text-sm flex items-center gap-2">
          <input type="checkbox" checked={autoSchedule} onChange={(e) => setAutoSchedule(e.target.checked)} />
          Сразу ставить в расписание
        </label>
        <div className="flex gap-2 flex-wrap">
          <button
            className="btn-primary"
            disabled={busy || !selectedId}
            onClick={async () => {
              if (!selectedId) return;
              setBusy(true);
              try {
                await api.factory.updateBrief(selectedId, brief);
                await api.factory.plan(selectedId, {
                  count,
                  duration_s: duration,
                  auto_schedule: autoSchedule,
                });
                push("План поставлен в очередь", "success", {
                  label: "Открыть",
                  href: `/activity?lane=renders`,
                });
                await reload();
              } catch (err) {
                push(formatApiError(err), "error");
              } finally {
                setBusy(false);
              }
            }}
          >
            <Calendar className="h-4 w-4" />
            Запланировать
          </button>
          <button
            className="btn-ghost"
            disabled={busy || !selectedId}
            onClick={async () => {
              if (!selectedId) return;
              setBusy(true);
              try {
                await api.factory.updateBrief(selectedId, brief);
                await api.factory.week(selectedId, { count, duration_s: duration, auto_schedule: autoSchedule });
                push("План на неделю поставлен в очередь", "success");
                await reload();
              } catch (err) {
                push(formatApiError(err), "error");
              } finally {
                setBusy(false);
              }
            }}
          >
            <CalendarDays className="h-4 w-4" />
            План на неделю
          </button>
          <button
            className="btn-ghost"
            disabled={busy || !selectedId}
            onClick={async () => {
              if (!selectedId) return;
              setBusy(true);
              try {
                await api.factory.updateBrief(selectedId, brief);
                const out = await api.factory.preview(selectedId, { count, duration_s: duration });
                push(
                  `Превью: ${out.planned} ролик(ов) в очереди рендера, без PlanJob и календаря`,
                  "success"
                );
                await reload();
              } catch (err) {
                push(formatApiError(err), "error");
              } finally {
                setBusy(false);
              }
            }}
          >
            <Eye className="h-4 w-4" />
            Превью
          </button>
        </div>
      </Card>
      <Card className="p-4 space-y-3">
        <h2 className="font-medium">Источники</h2>
        <div className="flex gap-2">
          <input className="input" placeholder="https://…" value={sourceValue} onChange={(e) => setSourceValue(e.target.value)} />
          <button
            className="btn-ghost shrink-0"
            disabled={!selectedId || !sourceValue.trim()}
            onClick={async () => {
              if (!selectedId) return;
              try {
                await api.factory.addSource(selectedId, { kind: "url", value: sourceValue.trim() });
                setSourceValue("");
                setSources(await api.factory.sources(selectedId));
              } catch (err) {
                push(formatApiError(err), "error");
              }
            }}
          >
            <Plus className="h-4 w-4" />
            Добавить
          </button>
        </div>
        {sources.length === 0 ? <EmptyState>пока пусто</EmptyState> : null}
        <ul className="text-sm space-y-2">
          {sources.map((s) => (
            <li key={s.id} className="flex items-center gap-2 text-slate-400">
              <label className="flex items-center gap-2 min-w-0 flex-1">
                <input
                  type="checkbox"
                  checked={s.enabled}
                  onChange={async (e) => {
                    await api.factory.patchSource(s.id, { enabled: e.target.checked });
                    if (selectedId) setSources(await api.factory.sources(selectedId));
                  }}
                />
                <span className="truncate">{s.label || s.value}</span>
              </label>
              <span className="text-xs text-slate-500">{s.last_status}</span>
              <button
                className="btn-ghost text-xs"
                onClick={async () => {
                  try {
                    const out = await api.factory.checkSource(s.id);
                    push(out.last_status === "ok" ? "Источник читается" : out.last_status, out.last_status === "ok" ? "success" : "error");
                    if (selectedId) setSources(await api.factory.sources(selectedId));
                  } catch (err) {
                    push(formatApiError(err), "error");
                  }
                }}
              >
                Проверить
              </button>
            </li>
          ))}
        </ul>
      </Card>
      <Card className="p-4 space-y-3">
        <h2 className="font-medium">Планы</h2>
        {plans.length === 0 ? (
          <EmptyState>Планов пока нет.</EmptyState>
        ) : (
          <ul className="text-sm space-y-2">
            {plans.map((p) => (
              <li key={p.id} className="flex items-center gap-2 border-t border-slate-800 pt-2">
                <span className="tabular-nums text-slate-500">#{p.id}</span>
                <StatusBadge value={p.status} />
                <span className="text-slate-400">
                  {p.planned}/{p.count}
                  {p.spread_over_days ? ` · ${p.spread_over_days}д` : ""}
                </span>
                <span className="min-w-0 flex-1 truncate text-xs text-rose-300" title={p.last_error ?? ""}>
                  {p.last_error || ""}
                </span>
                {["queued", "failed", "dead"].includes(p.status) ? (
                  <button
                    type="button"
                    className="btn-ghost btn-compact"
                    aria-label={`Отменить план ${p.id}`}
                    onClick={async () => {
                      try {
                        await api.factory.cancelPlan(p.id);
                        push(`План #${p.id} отменён`, "info");
                        if (selectedId) setPlans(await api.factory.plans(selectedId));
                      } catch (err) {
                        push(formatApiError(err), "error");
                      }
                    }}
                  >
                    <Ban className="h-3.5 w-3.5" />
                    Отменить
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </Card>
      {questions.length > 0 ? (
        <Card className="p-4 space-y-3">
          <h2 className="font-medium">Вопросы агента</h2>
          {questions.map((q) => (
            <div key={q.id} className="text-sm border-t border-slate-800 pt-2 space-y-2">
              <div>{q.question}</div>
              <div className="text-xs text-slate-500">Предположение: {q.assumed}</div>
              <div className="flex gap-2">
                <input
                  className="input"
                  placeholder="Ответ"
                  value={answers[q.id] ?? ""}
                  onChange={(e) => setAnswers((cur) => ({ ...cur, [q.id]: e.target.value }))}
                />
                <button
                  className="btn-primary shrink-0"
                  disabled={!answers[q.id]?.trim()}
                  onClick={async () => {
                    try {
                      await api.factory.answerQuestion(q.id, answers[q.id].trim());
                      push("Ответ записан", "success");
                      if (selectedId) setQuestions(await api.factory.questions(selectedId));
                      refreshNavBadges();
                    } catch (err) {
                      push(formatApiError(err), "error");
                    }
                  }}
                >
                  <Send className="h-4 w-4" />
                  Ответить
                </button>
              </div>
            </div>
          ))}
        </Card>
      ) : null}
      <Card className="p-4">
        <h2 className="font-medium mb-3">Прогоны</h2>
        {busy ? <Loader label="Загрузка..." /> : null}
        <table className="table-base">
          <thead>
            <tr>
              <th>Когда</th>
              <th>Аккаунт</th>
              <th>Модель</th>
              <th>Идеи</th>
              <th>$</th>
              <th>Статус</th>
            </tr>
          </thead>
          <tbody>
            {runs.length === 0 ? (
              <tr>
                <td colSpan={6}>
                  <EmptyState>пока пусто</EmptyState>
                </td>
              </tr>
            ) : null}
            {runs.map((r) => (
              <tr
                key={r.id}
                className="cursor-pointer hover:bg-slate-900/50"
                onClick={async () => {
                  try {
                    setRunDetail(await api.factory.agentRun(r.id));
                  } catch (err) {
                    push(formatApiError(err), "error");
                  }
                }}
              >
                <td className="truncate text-[11px] text-slate-400" title={r.created_at}>
                  {r.created_at}
                </td>
                <td className="truncate">{r.account_username}</td>
                <td className="truncate" title={r.model}>
                  {r.model}
                </td>
                <td>
                  {r.returned}/{r.requested}
                </td>
                <td className="tabular-nums">{r.cost_usd}</td>
                <td className="truncate" title={r.ok ? "ok" : r.error ?? ""}>
                  {r.ok ? "ok" : r.error}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      {runDetail ? (
        <Modal open title={`Прогон #${runDetail.id}`} onClose={() => setRunDetail(null)}>
          <div className="space-y-3 text-sm">
            <div className="text-slate-400">${runDetail.cost_usd}</div>
            {runDetail.error ? <div className="text-rose-300">{runDetail.error}</div> : null}
            <pre className="whitespace-pre-wrap text-xs bg-slate-900 p-3 rounded-lg max-h-48 overflow-auto">{runDetail.prompt}</pre>
            <pre className="whitespace-pre-wrap text-xs bg-slate-900 p-3 rounded-lg max-h-48 overflow-auto">
              {JSON.stringify(runDetail.ideas, null, 2)}
            </pre>
          </div>
        </Modal>
      ) : null}
    </div>
  );
}
