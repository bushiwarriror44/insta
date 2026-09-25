import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { Pencil, Send, Sparkle, Trash2 } from "lucide-react";
import clsx from "clsx";
import { useLocation, useNavigate } from "react-router-dom";

import { api, formatApiError } from "../api/client";
import { ask } from "../api/assistant";
import { library, search, type PromptGroup } from "../api/prompts";
import { CHAT_MANUAL, pageHint, toolHint } from "../lib/agentManual";
import { emitAssistantMutate } from "../lib/assistantMutate";
import { panelPath } from "../lib/panelHref";
import { SHOW_ASSISTANT } from "../lib/uiEvents";

const HIDDEN_KEY = "assistant-dock:hidden";
const THREAD_KEY = "assistant-dock:thread";
const CHATS_KEY = "assistant-dock:chats";

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
  diagnose: "посмотрел постинг, вход и прокси",
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
  generate_wan: "поставил ролик на Wan",
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

const CUT_LINE = "Ответ оборвался на шлюзе.";
const FORMAT_LINE = "хост модели отклонил формат запроса. Напишите ещё раз.";
const MEDIA_PHRASE = "unsupported media type";

function onlyMediaPhrase(text: string): boolean {
  const trimmed = text.trim().toLowerCase();
  if (!trimmed.includes(MEDIA_PHRASE)) return false;
  const rest = trimmed.split(MEDIA_PHRASE).join("");
  return rest.replace(/[\s.:;,\-]/g, "") === "";
}

interface Said {
  role: "user" | "assistant";
  content: string;
  used?: string[];
  images?: string[];
  thinking?: string;
  steps?: string[];
  cut?: string;
}

function Reason({ text, live }: { text: string; live: boolean }) {
  const [open, setOpen] = useState(live);
  const wasLive = useRef(live);
  useEffect(() => {
    if (live && !wasLive.current) setOpen(true);
    if (!live && wasLive.current) setOpen(false);
    wasLive.current = live;
  }, [live]);
  if (!text.trim()) return null;
  return (
    <details
      open={open}
      onToggle={(event) => setOpen((event.target as HTMLDetailsElement).open)}
      className="mb-1"
    >
      <summary className="cursor-pointer text-xs text-slate-500">Рассуждение</summary>
      <p className="mt-1 max-h-36 overflow-y-auto whitespace-pre-wrap text-xs text-slate-400">{text}</p>
    </details>
  );
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

interface Chat {
  id: string;
  title: string;
  customTitle: boolean;
  messages: Said[];
}

interface Live {
  busy: boolean;
  writing: string;
  think: string;
  doing: string[];
  doingName: string | null;
  pending: string[];
  seconds: number;
  asks: string[];
  askAnswers: Record<number, string>;
  note: string | null;
}

function emptyLive(): Live {
  return {
    busy: false,
    writing: "",
    think: "",
    doing: [],
    doingName: null,
    pending: [],
    seconds: 0,
    asks: [],
    askAnswers: {},
    note: null,
  };
}

function chatId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return `chat-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function titleFrom(messages: Said[]): string {
  const text = messages.find((message) => message.role === "user")?.content.replace(/\s+/g, " ").trim() ?? "";
  if (!text) return "Новый чат";
  return text.length > 32 ? `${text.slice(0, 32)}…` : text;
}

function blankChat(messages: Said[] = []): Chat {
  return { id: chatId(), title: titleFrom(messages), customTitle: false, messages };
}

function withAutoTitle(chat: Chat, messages: Said[]): Chat {
  if (chat.customTitle) return { ...chat, messages };
  return { ...chat, messages, title: titleFrom(messages) };
}

function readLegacyThread(): Said[] {
  try {
    const raw = window.localStorage.getItem(THREAD_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as Said[];
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((message) => message && (message.role === "user" || message.role === "assistant") && typeof message.content === "string")
      .slice(-40);
  } catch {
    return [];
  }
}

function readStore(): { activeId: string; chats: Chat[] } {
  try {
    const raw = window.localStorage.getItem(CHATS_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as { activeId?: string; chats?: Chat[] };
      const chats = (parsed.chats ?? [])
        .filter((chat) => chat && typeof chat.id === "string" && Array.isArray(chat.messages))
        .map((chat) => ({
          id: chat.id,
          title: typeof chat.title === "string" && chat.title.trim() ? chat.title : titleFrom(chat.messages),
          customTitle: Boolean(chat.customTitle),
          messages: chat.messages
            .filter((message) => message && (message.role === "user" || message.role === "assistant") && typeof message.content === "string")
            .slice(-40),
        }));
      if (chats.length) {
        const activeId = chats.some((chat) => chat.id === parsed.activeId) ? (parsed.activeId as string) : chats[0].id;
        return { activeId, chats };
      }
    }
  } catch {
    /* fall through to the old single thread */
  }
  const chat = blankChat(readLegacyThread());
  return { activeId: chat.id, chats: [chat] };
}

function writeStore(chats: Chat[], activeId: string) {
  try {
    const slim = {
      activeId,
      chats: chats.map((chat) => ({
        id: chat.id,
        title: chat.title,
        customTitle: chat.customTitle,
        messages: chat.messages.slice(-40).map(({ role, content, used, thinking, steps, cut, images }) => ({
          role,
          content,
          used,
          thinking,
          steps,
          cut,
          images,
        })),
      })),
    };
    window.localStorage.setItem(CHATS_KEY, JSON.stringify(slim));
    window.localStorage.removeItem(THREAD_KEY);
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
  const initial = useState(readStore)[0];
  const [chats, setChats] = useState<Chat[]>(initial.chats);
  const [activeId, setActiveId] = useState(initial.activeId);
  const [live, setLive] = useState<Record<string, Live>>({});
  const [draft, setDraft] = useState("");
  const [renaming, setRenaming] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const writingRef = useRef<Record<string, string>>({});
  const thinkRef = useRef<Record<string, string>>({});
  const doingRef = useRef<Record<string, string[]>>({});
  const stops = useRef<Record<string, AbortController>>({});
  const busyIds = useRef(new Set<string>());
  const chatsRef = useRef(chats);
  const activeRef = useRef(activeId);
  chatsRef.current = chats;
  activeRef.current = activeId;
  const [groups, setGroups] = useState<PromptGroup[]>(() => library([]));
  const [browsing, setBrowsing] = useState(false);
  const [readingManual, setReadingManual] = useState(false);
  const [needle, setNeedle] = useState("");
  const [hidden, setHidden] = useState(readHidden);

  const box = useRef<HTMLTextAreaElement>(null);
  const tail = useRef<HTMLDivElement>(null);

  useEffect(() => {
    onHiddenChange?.(hidden);
  }, [hidden, onHiddenChange]);

  useEffect(() => {
    writeStore(chats, activeId);
  }, [chats, activeId]);

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
    const tick = window.setInterval(() => {
      setLive((prev) => {
        let changed = false;
        const next = { ...prev };
        for (const id of busyIds.current) {
          const current = next[id];
          if (!current?.busy) continue;
          next[id] = { ...current, seconds: current.seconds + 1 };
          changed = true;
        }
        return changed ? next : prev;
      });
    }, 1000);
    return () => window.clearInterval(tick);
  }, []);

  useEffect(() => () => {
    for (const controller of Object.values(stops.current)) controller.abort();
  }, []);

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

  const replaceMessages = useCallback((id: string, messages: Said[]) => {
    setChats((prev) => prev.map((item) => (item.id === id ? withAutoTitle(item, messages) : item)));
  }, []);

  const patchLive = useCallback((id: string, patch: Partial<Live>) => {
    setLive((prev) => ({ ...prev, [id]: { ...(prev[id] ?? emptyLive()), ...patch } }));
  }, []);

  const send = useCallback(
    async (text: string) => {
      const question = text.trim();
      const id = activeRef.current;
      const chat = chatsRef.current.find((item) => item.id === id);
      if (!question || !chat || busyIds.current.has(id)) return;
      const asked: Said[] = [...chat.messages, { role: "user", content: question }];
      const notes: Said[] = [];
      const pushStatus = (line: string) => {
        if (notes.some((item) => item.content === line)) return;
        notes.push({ role: "assistant", content: line });
        replaceMessages(id, [...asked, ...notes]);
      };
      replaceMessages(id, asked);
      setDraft("");
      writingRef.current[id] = "";
      thinkRef.current[id] = "";
      doingRef.current[id] = [];
      patchLive(id, {
        note: null,
        asks: [],
        askAnswers: {},
        doing: [],
        doingName: null,
        writing: "",
        think: "",
        pending: [],
        seconds: 0,
        busy: true,
      });
      setBrowsing(false);
      setReadingManual(false);
      busyIds.current.add(id);
      const controller = new AbortController();
      stops.current[id] = controller;
      let answered = false;
      const keepPartial = (detail: string) => {
        const printed = writingRef.current[id] ?? "";
        const thinking = (thinkRef.current[id] ?? "").trim();
        const steps = doingRef.current[id] ?? [];
        const media = onlyMediaPhrase(printed);
        const kept = Boolean(printed || thinking || steps.length);
        answered = true;
        replaceMessages(id, [
          ...asked,
          ...notes,
          {
            role: "assistant",
            content: media ? FORMAT_LINE : printed || (kept ? "" : detail),
            thinking: thinking || undefined,
            steps: steps.length ? steps : undefined,
            cut: media ? undefined : printed || thinking ? CUT_LINE : undefined,
          },
        ]);
      };
      try {
        await ask(
          asked.map(({ role, content }) => ({ role, content })),
          (step) => {
            if (controller.signal.aborted) return;
            if (step.type === "status") {
              pushStatus(step.text);
            } else if (step.type === "tool") {
              doingRef.current[id] = [...(doingRef.current[id] ?? []), step.text];
              patchLive(id, { doing: doingRef.current[id], doingName: step.name ?? null });
            } else if (step.type === "think") {
              thinkRef.current[id] = (thinkRef.current[id] ?? "") + step.text;
              patchLive(id, { think: thinkRef.current[id] });
            } else if (step.type === "token") {
              writingRef.current[id] = (writingRef.current[id] ?? "") + step.text;
              patchLive(id, { writing: writingRef.current[id] });
            } else if (step.type === "image") {
              setLive((prev) => {
                const current = prev[id] ?? emptyLive();
                return { ...prev, [id]: { ...current, pending: [...current.pending, step.text] } };
              });
            } else if (step.type === "ask") {
              patchLive(id, { asks: step.questions ?? [], askAnswers: {} });
            } else if (step.type === "error") {
              if (writingRef.current[id] || (thinkRef.current[id] ?? "").trim() || (doingRef.current[id] ?? []).length) {
                keepPartial(step.detail);
              } else {
                answered = true;
                replaceMessages(id, [...asked, ...notes, { role: "assistant", content: step.detail }]);
              }
            } else if (step.type === "done") {
              answered = true;
              const thinking = (step.thinking || thinkRef.current[id] || "").trim();
              const reply = onlyMediaPhrase(step.reply) ? FORMAT_LINE : step.reply;
              replaceMessages(id, [
                ...asked,
                ...notes,
                {
                  role: "assistant",
                  content: reply,
                  used: step.used,
                  images: step.images,
                  thinking: thinking || undefined,
                  cut: step.cut || undefined,
                },
              ]);
              if (step.asks?.length) patchLive(id, { asks: step.asks, askAnswers: {} });
              if (step.used?.some((name) => MUTATE_TOOLS.has(name))) {
                emitAssistantMutate(step.created);
              }
              if (step.open_url) {
                if (!step.reply.trim()) {
                  patchLive(id, { note: step.opened ? `Открыл: ${step.opened}` : "Открыл" });
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
          if (writingRef.current[id] || (thinkRef.current[id] ?? "").trim() || (doingRef.current[id] ?? []).length) {
            keepPartial(formatApiError(err));
          } else {
            replaceMessages(id, [...asked, ...notes, { role: "assistant", content: formatApiError(err) }]);
            answered = true;
          }
        }
      } finally {
        if (!answered && !controller.signal.aborted) {
          if (writingRef.current[id] || (thinkRef.current[id] ?? "").trim() || (doingRef.current[id] ?? []).length) {
            keepPartial("Ответа не было.");
          } else {
            replaceMessages(id, [...asked, ...notes, { role: "assistant", content: "Ответа не было." }]);
          }
        }
        if (stops.current[id] === controller) delete stops.current[id];
        busyIds.current.delete(id);
        writingRef.current[id] = "";
        thinkRef.current[id] = "";
        doingRef.current[id] = [];
        patchLive(id, {
          busy: false,
          writing: "",
          think: "",
          doing: [],
          doingName: null,
          pending: [],
        });
        if (activeRef.current === id) box.current?.focus();
      }
    },
    [page, accountId, jobId, navigate, replaceMessages, patchLive]
  );

  const chat = chats.find((item) => item.id === activeId) ?? chats[0];
  const thread = chat?.messages ?? [];
  const view = (chat && live[chat.id]) || emptyLive();
  const busy = view.busy;
  const writing = view.writing;
  const draftThink = view.think;
  const doing = view.doing;
  const doingName = view.doingName;
  const pending = view.pending;
  const seconds = view.seconds;
  const asks = view.asks;
  const askAnswers = view.askAnswers;
  const note = view.note;
  const anyBusy = Object.values(live).some((item) => item.busy);

  const setAskAnswers = (
    update: Record<number, string> | ((prev: Record<number, string>) => Record<number, string>)
  ) => {
    if (!chat) return;
    const id = chat.id;
    setLive((prev) => {
      const current = prev[id] ?? emptyLive();
      const next = typeof update === "function" ? update(current.askAnswers) : update;
      return { ...prev, [id]: { ...current, askAnswers: next } };
    });
  };

  const startChat = () => {
    const created = blankChat();
    setChats((prev) => [...prev, created]);
    setActiveId(created.id);
    setRenaming(null);
  };

  const beginRename = (item: Chat) => {
    setRenaming(item.id);
    setRenameDraft(item.title);
  };

  const commitRename = () => {
    const id = renaming;
    if (!id) return;
    const name = renameDraft.trim() || "Новый чат";
    setChats((prev) => prev.map((item) => (item.id === id ? { ...item, title: name, customTitle: true } : item)));
    setRenaming(null);
  };

  const clearActive = () => {
    if (!chat) return;
    const id = chat.id;
    stops.current[id]?.abort();
    writingRef.current[id] = "";
    thinkRef.current[id] = "";
    doingRef.current[id] = [];
    busyIds.current.delete(id);
    setChats((prev) =>
      prev.map((item) =>
        item.id === id ? { ...item, messages: [], title: item.customTitle ? item.title : "Новый чат" } : item
      )
    );
    setLive((prev) => ({ ...prev, [id]: emptyLive() }));
  };

  useEffect(() => {
    tail.current?.scrollIntoView?.({ block: "end" });
  }, [thread, writing, draftThink, doing, pending, asks, askAnswers]);

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
            {anyBusy ? <ThinkingSparkle quiet /> : <Sparkle size={16} className="text-sky-300" />}
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
                {message.role === "assistant" && message.thinking ? (
                  <Reason text={message.thinking} live={false} />
                ) : null}
                {message.content ? (
                  <p className={message.role === "user" ? "text-sm text-slate-400" : "whitespace-pre-wrap text-sm text-slate-100"}>
                    {message.role === "user" && <span className="mr-2 text-xs text-slate-600">вы</span>}
                    {message.content}
                  </p>
                ) : null}
                {message.cut ? <p className="mt-1 text-xs text-slate-500">{message.cut}</p> : null}
                {message.steps && message.steps.length > 0 && (
                  <div className="mt-1 space-y-0.5">
                    {message.steps.map((what, i) => (
                      <p key={i} className="text-xs text-slate-600">
                        {what}
                      </p>
                    ))}
                  </div>
                )}
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
                  <span>
                    {writing
                      ? "Пишет…"
                      : draftThink
                        ? "Рассуждает…"
                        : doing.length
                          ? doing[doing.length - 1]
                          : `Думает… ${seconds} с`}
                  </span>
                </div>
                {!writing && doingName && toolHint(doingName) ? (
                  <p data-testid="assistant-tool-hint" className="text-xs text-slate-500">
                    {toolHint(doingName)}
                  </p>
                ) : null}
                {draftThink ? <Reason text={draftThink} live={!writing} /> : null}
                {writing ? (
                  <p className="whitespace-pre-wrap text-sm text-slate-100">{writing}</p>
                ) : null}
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
          <div className="mb-2 flex items-center gap-1 overflow-x-auto" role="tablist" aria-label="Чаты">
            <button type="button" onClick={startChat} className="btn-ghost shrink-0 text-xs">
              Новый
            </button>
            {chats.map((item) =>
              renaming === item.id ? (
                <input
                  key={item.id}
                  aria-label="Название чата"
                  value={renameDraft}
                  onChange={(event) => setRenameDraft(event.target.value)}
                  onBlur={commitRename}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      commitRename();
                    }
                  }}
                  className="input h-7 w-36 shrink-0 text-xs"
                  autoFocus
                />
              ) : (
                <span key={item.id} className="flex shrink-0 items-center">
                  <button
                    type="button"
                    role="tab"
                    aria-selected={item.id === activeId}
                    onClick={() => {
                      setActiveId(item.id);
                      setRenaming(null);
                    }}
                    className={clsx(
                      "rounded-full px-2 py-1 text-xs",
                      item.id === activeId ? "bg-slate-800 text-slate-100" : "text-slate-400 hover:text-slate-200"
                    )}
                  >
                    {item.title}
                    {live[item.id]?.busy ? " …" : ""}
                  </button>
                  {item.id === activeId && (
                    <button
                      type="button"
                      aria-label="Переименовать чат"
                      onClick={() => beginRename(item)}
                      className="btn-ghost px-1 py-1"
                    >
                      <Pencil className="h-3 w-3" />
                    </button>
                  )}
                </span>
              )
            )}
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2 px-1 pb-2">
            <div className="min-w-0 flex-1 space-y-1">
              <div className="flex items-center gap-2">
                {busy && <ThinkingSparkle quiet={Boolean(writing)} />}
                <h2 className="text-xs font-semibold text-slate-300">Спросить агента</h2>
              </div>
              {!busy ? (
                <p data-testid="assistant-page-hint" className="text-xs text-slate-500">
                  {pageHint(page)}
                </p>
              ) : null}
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
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setBrowsing((seen) => !seen);
                    setReadingManual(false);
                  }}
                  className="btn-ghost text-xs"
                >
                  {browsing ? "Скрыть примеры" : "Что можно спросить"}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setReadingManual((seen) => !seen);
                    setBrowsing(false);
                  }}
                  className="btn-ghost text-xs"
                >
                  {readingManual ? "Скрыть мануал" : "Мануал"}
                </button>
              </div>
              <div className="flex items-center gap-2">
                {busy && (
                  <button type="button" onClick={() => stops.current[activeId]?.abort()} className="btn-ghost">
                    Остановить
                  </button>
                )}
                {(thread.length > 0 || busy) && (
                  <button type="button" onClick={clearActive} className="btn-ghost">
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
          {readingManual && (
            <div
              className="mt-3 max-h-64 space-y-3 overflow-y-auto rounded-lg border border-slate-800 bg-slate-950/50 p-4"
              data-testid="assistant-manual"
            >
              {CHAT_MANUAL.map((section) => (
                <div key={section.id}>
                  <h3 className="text-xs font-medium text-slate-300">{section.title}</h3>
                  <div className="mt-1 space-y-1.5 text-xs leading-relaxed text-slate-400">
                    {section.body.map((paragraph) => (
                      <p key={paragraph}>{paragraph}</p>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
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
