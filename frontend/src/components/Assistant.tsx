import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { Send, Sparkle, Trash2 } from "lucide-react";
import clsx from "clsx";
import { useLocation, useNavigate } from "react-router-dom";

import { api, formatApiError } from "../api/client";
import { ask } from "../api/assistant";
import { library, search, type PromptGroup } from "../api/prompts";
import { emitAssistantMutate } from "../lib/assistantMutate";
import { panelPath } from "../lib/panelHref";
import { SHOW_ASSISTANT } from "../lib/uiEvents";

const HIDDEN_KEY = "assistant-dock:hidden";
const THREAD_KEY = "assistant-dock:thread";

const LOOKED_AT: Record<string, string> = {
  overview: "посчитал всё",
  list_accounts: "посмотрел аккаунты",
  account_details: "открыл секреты аккаунта",
  list_posts: "посмотрел публикации",
  list_clips: "поискал в библиотеке",
  list_renders: "посмотрел рендеры",
  list_compositions: "посмотрел склейки",
  list_proxies: "посмотрел прокси",
  list_errors: "посмотрел ошибки",
  list_operators: "посмотрел доступы",
  list_project_files: "посмотрел файлы проекта",
  read_project_file: "прочитал файл",
  job_logs: "прочитал логи",
  account_logs: "прочитал логи аккаунта",
  open_page: "открыл страницу",
  open_clip: "нашёл клип",
  open_post: "нашёл публикацию",
  open_account: "нашёл аккаунт",
  screenshot_page: "сделал снимок страницы",
  plan_account: "поставил план",
  preview_plan: "посмотрел превью плана",
  enqueue_publish: "поставил публикацию",
  reschedule_job: "перенёс слот",
  pause_account: "поставил на паузу",
  resume_account: "снял с паузы",
  answer_question: "ответил на вопрос",
  add_source: "добавил источник",
  create_account: "добавил аккаунт",
  create_accounts: "добавил аккаунты",
  update_account: "обновил аккаунт",
  create_proxy: "добавил прокси",
  create_proxies: "добавил прокси",
  update_proxy: "обновил прокси",
  attach_proxy: "привязал прокси",
  page_guide: "посмотрел справочник страницы",
  ask_operator: "уточнил",
  diagnose: "посмотрел стек и логи",
  docker_logs: "прочитал логи docker",
  approve_job: "одобрил публикацию",
  cancel_job: "отменил публикацию",
  retry_job: "повторил публикацию",
  start_worker: "запустил воркер",
  stop_worker: "остановил воркер",
  take_backup: "снял копию базы",
  test_proxy: "проверил прокси",
  test_proxies: "проверил прокси",
  test_connection: "проверил подключение",
  test_connections: "проверил подключения",
  export_cookies: "выгрузил cookies",
  export_fingerprint: "выгрузил fingerprint",
  export_playwright_state: "выгрузил Playwright state",
  import_cookies: "импортировал cookies",
  import_fingerprint: "импортировал fingerprint",
  get_session: "прочитал сессию",
  publish_now: "поставил публикацию",
  first_login: "сделал автовход",
  mint_mobile_session: "выпустил mobile-сессию",
  retry_render: "повторил рендер",
  cancel_render: "отменил рендер",
  create_render: "поставил рендер",
  compose: "поставил склейку",
  cancel_composition: "отменил склейку",
  retry_composition: "повторил склейку",
  check_source: "проверил источник",
  refresh_stats: "обновил статистику",
};

const MUTATE_TOOLS = new Set([
  "create_account",
  "create_accounts",
  "update_account",
  "create_proxy",
  "create_proxies",
  "update_proxy",
  "attach_proxy",
  "approve_job",
  "cancel_job",
  "retry_job",
  "start_worker",
  "stop_worker",
  "take_backup",
  "test_proxy",
  "test_proxies",
  "test_connection",
  "test_connections",
  "import_cookies",
  "import_fingerprint",
  "publish_now",
  "first_login",
  "mint_mobile_session",
  "retry_render",
  "cancel_render",
  "create_render",
  "compose",
  "cancel_composition",
  "retry_composition",
  "check_source",
  "refresh_stats",
  "preview_plan",
  "reschedule_job",
  "pause_account",
  "resume_account",
  "enqueue_publish",
  "plan_account",
]);

interface Said {
  role: "user" | "assistant";
  content: string;
  used?: string[];
  images?: string[];
}

function openInPlace(navigate: (to: string) => void, url: string) {
  if (url.startsWith("http")) {
    const parsed = new URL(url);
    navigate(`${panelPath(parsed.pathname)}${parsed.search}`);
    return;
  }
  const [path, search] = url.split("?");
  navigate(`${panelPath(path)}${search ? `?${search}` : ""}`);
}

function readThread(): Said[] {
  try {
    const raw = window.localStorage.getItem(THREAD_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as Said[];
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((m) => m && (m.role === "user" || m.role === "assistant") && typeof m.content === "string")
      .slice(-40);
  } catch {
    return [];
  }
}

function writeThread(thread: Said[]) {
  try {
    const slim = thread.slice(-40).map(({ role, content, used }) => ({ role, content, used }));
    window.localStorage.setItem(THREAD_KEY, JSON.stringify(slim));
  } catch {
    /* ignore quota / private mode */
  }
}

function readHidden(): boolean {
  try {
    return window.localStorage.getItem(HIDDEN_KEY) === "1";
  } catch {
    return false;
  }
}

function writeHidden(hidden: boolean) {
  try {
    window.localStorage.setItem(HIDDEN_KEY, hidden ? "1" : "0");
  } catch {
    /* ignore quota / private mode */
  }
}

function ThinkingSparkle({ quiet = false }: { quiet?: boolean }) {
  return (
    <Sparkle
      size={16}
      data-testid="assistant-sparkle"
      aria-label="агент работает"
      className={clsx("shrink-0 text-sky-300", "assistant-sparkle", quiet && "assistant-sparkle-quiet")}
    />
  );
}

interface AssistantProps {
  onHiddenChange?: (hidden: boolean) => void;
}

export function Assistant({ onHiddenChange }: AssistantProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const page = panelPath(location.pathname);
  const params = new URLSearchParams(location.search);
  const accountId = Number(params.get("id") || 0) || undefined;
  const jobId = Number(params.get("job") || 0) || undefined;
  const [thread, setThread] = useState<Said[]>(readThread);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [doing, setDoing] = useState<string[]>([]);
  const [writing, setWriting] = useState("");
  const [pending, setPending] = useState<string[]>([]);
  const [seconds, setSeconds] = useState(0);
  const [note, setNote] = useState<string | null>(null);
  const [groups, setGroups] = useState<PromptGroup[]>(() => library([]));
  const [browsing, setBrowsing] = useState(false);
  const [needle, setNeedle] = useState("");
  const [hidden, setHidden] = useState(readHidden);
  const [asks, setAsks] = useState<string[]>([]);
  const [askAnswers, setAskAnswers] = useState<Record<number, string>>({});

  const box = useRef<HTMLTextAreaElement>(null);
  const tail = useRef<HTMLDivElement>(null);
  const stop = useRef<AbortController | null>(null);

  useEffect(() => {
    onHiddenChange?.(hidden);
  }, [hidden, onHiddenChange]);

  useEffect(() => {
    writeThread(thread);
  }, [thread]);

  useEffect(() => {
    let dropped = false;
    api.accounts
      .list()
      .then((accounts) => {
        if (!dropped) setGroups(library(accounts.map((a) => a.username)));
      })
      .catch(() => undefined);
    return () => {
      dropped = true;
    };
  }, []);

  useEffect(() => {
    if (!busy) return;
    setSeconds(0);
    const tick = setInterval(() => setSeconds((n) => n + 1), 1000);
    return () => clearInterval(tick);
  }, [busy]);

  useEffect(() => {
    tail.current?.scrollIntoView?.({ block: "end" });
  }, [thread, writing, doing, pending, asks, askAnswers]);

  useEffect(() => () => stop.current?.abort(), []);

  const hide = () => {
    setHidden(true);
    writeHidden(true);
  };

  const show = () => {
    setHidden(false);
    writeHidden(false);
    window.setTimeout(() => box.current?.focus(), 0);
  };

  useEffect(() => {
    const onShow = () => {
      setHidden(false);
      writeHidden(false);
      window.setTimeout(() => box.current?.focus(), 0);
    };
    window.addEventListener(SHOW_ASSISTANT, onShow);
    return () => window.removeEventListener(SHOW_ASSISTANT, onShow);
  }, []);

  const send = useCallback(
    async (text: string) => {
      const question = text.trim();
      if (!question || busy) return;
      const asked: Said[] = [...thread, { role: "user", content: question }];
      setThread(asked);
      setDraft("");
      setNote(null);
      setAsks([]);
      setAskAnswers({});
      setDoing([]);
      setWriting("");
      setPending([]);
      setBrowsing(false);
      setBusy(true);
      const controller = new AbortController();
      stop.current = controller;
      let answered = false;
      try {
        await ask(
          asked.map(({ role, content }) => ({ role, content })),
          (step) => {
            if (step.type === "tool") {
              setDoing((seen) => [...seen, step.text]);
            } else if (step.type === "token") {
              setWriting((soFar) => soFar + step.text);
            } else if (step.type === "image") {
              setPending((seen) => [...seen, step.text]);
            } else if (step.type === "ask") {
              setAsks(step.questions ?? []);
              setAskAnswers({});
            } else if (step.type === "error") {
              answered = true;
              setThread([...asked, { role: "assistant", content: step.detail }]);
            } else if (step.type === "done") {
              answered = true;
              setThread([
                ...asked,
                {
                  role: "assistant",
                  content: step.reply,
                  used: step.used,
                  images: step.images,
                },
              ]);
              if (step.asks?.length) {
                setAsks(step.asks);
                setAskAnswers({});
              }
              if (step.used?.some((name) => MUTATE_TOOLS.has(name))) {
                emitAssistantMutate(step.created);
              }
              if (step.open_url) {
                if (!step.reply.trim()) {
                  setNote(step.opened ? `Открыл: ${step.opened}` : "Открыл");
                }
                openInPlace(navigate, step.open_url);
              }
            }
          },
          controller.signal,
          page,
          { account_id: accountId, job_id: jobId }
        );
      } catch (err) {
        if (!controller.signal.aborted) {
          setThread([...asked, { role: "assistant", content: formatApiError(err) }]);
          answered = true;
        }
      } finally {
        if (!answered && !controller.signal.aborted) {
          setThread([...asked, { role: "assistant", content: "Ответа не было." }]);
        }
        stop.current = null;
        setBusy(false);
        setWriting("");
        setDoing([]);
        setPending([]);
        box.current?.focus();
      }
    },
    [busy, thread, page, accountId, jobId, navigate]
  );

  const answerAsks = (e: FormEvent) => {
    e.preventDefault();
    const lines = asks.map((question, i) => `${question}: ${(askAnswers[i] ?? "").trim()}`);
    if (lines.some((line) => line.endsWith(":"))) return;
    void send(`Уточнения:\n${lines.join("\n")}`);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send(draft);
    }
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void send(draft);
  };

  const shown = search(groups, needle);
  const open = thread.length > 0 || busy || asks.length > 0;

  if (hidden) {
    return (
      <div className="pointer-events-none fixed inset-x-0 bottom-0 z-30 md:left-60">
        <div className="pointer-events-auto flex justify-end px-3 pb-3 sm:px-4 sm:pb-4">
          <button
            type="button"
            onClick={show}
            aria-label="Показать агента"
            className="flex items-center gap-2 rounded-full border border-slate-700 bg-slate-950/95 px-3 py-2 text-sm text-slate-200 shadow-xl backdrop-blur hover:border-slate-500"
          >
            {busy ? <ThinkingSparkle quiet={Boolean(writing)} /> : <Sparkle size={16} className="text-sky-300" />}
            <span>Агент</span>
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-0 z-30 md:left-60">
      <div className="pointer-events-auto mx-auto w-full max-w-3xl px-3 pb-3 sm:px-4 sm:pb-4">
        {open && (
          <div
            className="mb-2 max-h-[55vh] space-y-3 overflow-y-auto rounded-t-xl border border-slate-800 bg-slate-950/95 p-4 shadow-xl backdrop-blur"
            role="log"
            aria-label="Разговор"
          >
            {thread.map((message, n) => (
              <div key={n}>
                <p className={message.role === "user" ? "text-sm text-slate-400" : "whitespace-pre-wrap text-sm text-slate-100"}>
                  {message.role === "user" && <span className="mr-2 text-xs text-slate-600">вы</span>}
                  {message.content}
                </p>
                {message.used && message.used.length > 0 && (
                  <p className="mt-0.5 text-xs text-slate-600">
                    {[...new Set(message.used.map((t) => LOOKED_AT[t] ?? t))].join(", ")}
                  </p>
                )}
                {message.images && message.images.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-2">
                    {message.images.map((src, i) => (
                      <a key={i} href={src} target="_blank" rel="noopener noreferrer" className="block overflow-hidden rounded-lg border border-slate-800">
                        <img src={src} alt="Снимок страницы панели" className="h-28 w-auto" />
                      </a>
                    ))}
                  </div>
                )}
              </div>
            ))}
            {busy && (
              <div role="status" className="space-y-2">
                <div className="flex items-center gap-2 text-sm text-slate-400">
                  <ThinkingSparkle quiet={Boolean(writing)} />
                  <span>{writing ? "Пишет…" : doing.length ? doing[doing.length - 1] : `Думает… ${seconds} с`}</span>
                </div>
                {doing.map((what, n) => (
                  <p key={n} className="text-xs text-slate-400">
                    {what}
                  </p>
                ))}
                {pending.length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {pending.map((src, i) => (
                      <img key={i} src={src} alt="Снимок страницы панели" className="h-28 w-auto rounded-lg border border-slate-800" />
                    ))}
                  </div>
                )}
                {writing ? (
                  <p className="whitespace-pre-wrap text-sm text-slate-100">{writing}</p>
                ) : null}
              </div>
            )}
            {!busy && note && <p className="text-xs text-slate-400">{note}</p>}
            {!busy && asks.length > 0 && (
              <form onSubmit={answerAsks} className="space-y-2 rounded-lg border border-slate-800 bg-slate-900/80 p-3">
                <p className="text-xs text-slate-400">Нужны уточнения</p>
                {asks.map((question, i) => (
                  <label key={`${question}-${i}`} className="block space-y-1">
                    <span className="text-xs text-slate-300">{question}</span>
                    <input
                      className="input"
                      value={askAnswers[i] ?? ""}
                      onChange={(e) => setAskAnswers((prev) => ({ ...prev, [i]: e.target.value }))}
                      aria-label={question}
                    />
                  </label>
                ))}
                <button
                  type="submit"
                  className="btn-primary"
                  disabled={asks.some((_, i) => !(askAnswers[i] ?? "").trim())}
                >
                  <Send className="h-4 w-4" />
                  Ответить
                </button>
              </form>
            )}
            <div ref={tail} />
          </div>
        )}

        <div className={`card bg-slate-950/95 p-3 shadow-xl backdrop-blur ${open ? "rounded-t-none border-t-0" : ""}`}>
          <div className="flex flex-wrap items-center justify-between gap-2 px-1 pb-2">
            <div className="flex items-center gap-2">
              {busy && <ThinkingSparkle quiet={Boolean(writing)} />}
              <h2 className="text-xs font-semibold text-slate-300">Спросить агента</h2>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-600">открывает страницы здесь, в этой вкладке</span>
              <button type="button" onClick={hide} className="btn-ghost text-xs py-1 px-2">
                Скрыть
              </button>
            </div>
          </div>
          <form onSubmit={onSubmit}>
            <textarea
              ref={box}
              rows={1}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onKeyDown}
              disabled={busy}
              aria-label="Спросить агента"
              placeholder="Спросите, что здесь есть, или скажите поставить план / публикацию…"
              className="input resize-none min-h-[40px]"
            />
            <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
              <button type="button" onClick={() => setBrowsing((seen) => !seen)} className="btn-ghost text-xs">
                {browsing ? "Скрыть примеры" : "Что можно спросить"}
              </button>
              <div className="flex items-center gap-2">
                {busy && (
                  <button type="button" onClick={() => stop.current?.abort()} className="btn-ghost">
                    Остановить
                  </button>
                )}
                {thread.length > 0 && !busy && (
                  <button
                    type="button"
                    onClick={() => {
                      setThread([]);
                      setNote(null);
                    }}
                    className="btn-ghost"
                  >
                    <Trash2 className="h-4 w-4" />
                    Очистить
                  </button>
                )}
                <button type="submit" disabled={busy || !draft.trim()} className="btn-primary">
                  {busy ? (
                    <span className="inline-flex items-center gap-2">
                      <ThinkingSparkle quiet={Boolean(writing)} />
                      Думает…
                    </span>
                  ) : (
                    <>
                      <Send className="h-4 w-4" />
                      Спросить
                    </>
                  )}
                </button>
              </div>
            </div>
          </form>
          {browsing && (
            <div className="mt-3 max-h-64 space-y-4 overflow-y-auto rounded-lg border border-slate-800 bg-slate-950/50 p-4">
              <input
                type="search"
                value={needle}
                onChange={(e) => setNeedle(e.target.value)}
                aria-label="Поиск по примерам"
                placeholder="Поиск по примерам…"
                className="input py-1.5 text-xs"
              />
              {shown.length === 0 ? (
                <p className="text-xs text-slate-500">Ничего не нашлось.</p>
              ) : (
                shown.map((group) => (
                  <div key={group.title}>
                    <h3 className="text-xs font-medium text-slate-400">{group.title}</h3>
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {group.prompts.map((prompt) => (
                        <button
                          key={prompt.text}
                          type="button"
                          title={prompt.text}
                          onClick={() => void send(prompt.text)}
                          className="rounded-full border border-slate-700 px-3 py-1 text-xs text-slate-400 hover:text-slate-100"
                        >
                          {prompt.label}
                        </button>
                      ))}
                    </div>
                  </div>
                ))
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
