import { ApiError, API_BASE, getAuthHeaders } from "./client";

export type AskOption = string | { value: string; label: string };

export type AskField = {
  id: string;
  label: string;
  kind?: "text" | "password" | "select";
  options?: AskOption[];
  required?: boolean;
};

export type FormKind = "account" | "proxy" | "publish";

export type AssistantFocus = {
  account_id?: number;
  job_id?: number;
};

export type AssistantAskOptions = {
  allowBrowser?: boolean;
  clientChatId?: string;
};

export type AssistantMessageAttachment = {
  filename: string;
  media_type?: string;
  role?: string;
};

export type AssistantChatMessage = {
  role: string;
  content: string;
  attachments?: AssistantMessageAttachment[];
};

export type AssistantCardKind = "accounts" | "renders" | "clips";

export type AssistantCardBlock = {
  kind: AssistantCardKind;
  items: Array<Record<string, unknown>>;
};

export type AssistantBrowserTarget = {
  username: string;
  platform?: string;
  proxy_label?: string | null;
  login_surface?: string | null;
};

export type AssistantStep =
  | { type: "tool"; text: string; name?: string }
  | { type: "cards"; cards: AssistantCardBlock[] }
  | { type: "token"; text: string }
  | { type: "think"; text: string }
  | { type: "image"; text: string }
  | {
      type: "ask";
      text?: string;
      questions: string[];
      fields?: AskField[];
      form_kind?: FormKind | string;
    }
  | {
      type: "done";
      reply: string;
      open_url: string | null;
      opened: string | null;
      used: string[];
      images: string[];
      asks?: string[];
      fields?: AskField[];
      form_kind?: FormKind | string;
      created?: { accounts?: number[]; proxies?: number[] };
      thinking?: string;
      cut?: string;
      offer_local_switch?: { job_id: number; message: string } | null;
      cards?: AssistantCardBlock[];
      browser_target?: AssistantBrowserTarget | null;
    }
    | { type: "status"; text: string }
    | { type: "progress"; text: string; detail?: string; ratio?: number; name?: string }
    | { type: "wire"; text: string; detail?: string; name?: string }
    | { type: "generation"; text: string; detail?: string; name?: string }
    | { type: "error"; detail: string; retryable: boolean };

type JobSnapshot = {
  id: number;
  status: string;
  reply: string;
  error: string | null;
  note: string;
  result: Record<string, unknown> | null;
};

function delay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("aborted", "AbortError"));
      return;
    }
    const timer = window.setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      window.clearTimeout(timer);
      reject(new DOMException("aborted", "AbortError"));
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

async function readJob(id: number, signal?: AbortSignal): Promise<JobSnapshot> {
  const response = await fetch(`${API_BASE}/api/assistant/jobs/${id}`, {
    headers: getAuthHeaders(),
    signal,
  });
  if (!response.ok) {
    throw new ApiError(response.status, `Запрос не прошёл (${response.status})`);
  }
  return (await response.json()) as JobSnapshot;
}

function doneFrom(result: Record<string, unknown>, fallbackReply: string): AssistantStep {
  const text = (value: unknown) => (typeof value === "string" ? value : null);
  return {
    type: "done",
    reply: text(result.reply) ?? fallbackReply,
    open_url: text(result.open_url),
    opened: text(result.opened),
    used: Array.isArray(result.used) ? result.used.map(String) : [],
    images: Array.isArray(result.images) ? result.images.map(String) : [],
    asks: Array.isArray(result.asks) ? result.asks.map(String) : undefined,
    fields: Array.isArray(result.fields) ? (result.fields as AskField[]) : undefined,
    form_kind: text(result.form_kind) ?? undefined,
    created: (result.created as { accounts?: number[]; proxies?: number[] } | undefined) ?? undefined,
    thinking: text(result.thinking) ?? undefined,
    cut: text(result.cut) ?? undefined,
    offer_local_switch:
      (result.offer_local_switch as { job_id: number; message: string } | null | undefined) ?? null,
    cards: Array.isArray(result.cards) ? (result.cards as AssistantCardBlock[]) : undefined,
    browser_target: (result.browser_target as AssistantBrowserTarget | null | undefined) ?? null,
  };
}

async function followJob(
  id: number,
  onStep: (step: AssistantStep) => void,
  signal?: AbortSignal
): Promise<void> {
  let replySeen = "";
  let noteSeen = "";
  for (;;) {
    const snap = await readJob(id, signal);
    if (snap.note && snap.note !== noteSeen) {
      noteSeen = snap.note;
      onStep({ type: "status", text: snap.note });
    }
    if (
      (snap.status === "running" || snap.status === "paused") &&
      snap.reply.length > replySeen.length &&
      snap.reply.startsWith(replySeen)
    ) {
      onStep({ type: "token", text: snap.reply.slice(replySeen.length) });
      replySeen = snap.reply;
    }
    if (snap.status === "needs_user") {
      const fallback = snap.note || snap.reply;
      if (snap.result) onStep(doneFrom(snap.result, fallback));
      else onStep(doneFrom({ reply: fallback }, fallback));
      return;
    }
    if (snap.status === "done" || snap.status === "failed" || snap.status === "stopped") {
      if (snap.result) onStep(doneFrom(snap.result, snap.reply));
      else onStep({ type: "error", detail: snap.error || "выполнение остановлено", retryable: false });
      return;
    }
    await delay(400, signal);
  }
}

export async function ask(
  messages: AssistantChatMessage[],
  onStep: (step: AssistantStep) => void,
  signal?: AbortSignal,
  page?: string,
  focus?: AssistantFocus,
  options?: AssistantAskOptions
): Promise<void> {
  const headers = new Headers({ "Content-Type": "application/json", ...getAuthHeaders() });
  const response = await fetch(`${API_BASE}/api/assistant/jobs`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      messages,
      page,
      account_id: focus?.account_id,
      job_id: focus?.job_id,
      allow_browser: Boolean(options?.allowBrowser),
      client_chat_id: options?.clientChatId ?? "",
    }),
    signal,
  });
  if (!response.ok) {
    let detail = `Запрос не прошёл (${response.status})`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string" && body.detail.trim()) detail = body.detail;
    } catch {
      /* keep the status line */
    }
    throw new ApiError(response.status, detail);
  }
  const started = (await response.json()) as { id: number };
  try {
    await followJob(started.id, onStep, signal);
  } catch (err) {
    if (signal?.aborted) return;
    throw err;
  }
}
