import { ApiError, API_BASE, getAuthHeaders } from "./client";

export type AskField = {
  id: string;
  label: string;
  kind?: "text" | "password" | "select";
  options?: string[];
};

export type AssistantFocus = {
  account_id?: number;
  job_id?: number;
};

export type AssistantStep =
  | { type: "tool"; text: string; name?: string }
  | { type: "token"; text: string }
  | { type: "think"; text: string }
  | { type: "image"; text: string }
  | { type: "ask"; text?: string; questions: string[]; fields?: AskField[] }
  | {
      type: "done";
      reply: string;
      open_url: string | null;
      opened: string | null;
      used: string[];
      images: string[];
      asks?: string[];
      created?: { accounts?: number[]; proxies?: number[] };
      thinking?: string;
      cut?: string;
    }
    | { type: "status"; text: string }
    | { type: "progress"; text: string; detail?: string; ratio?: number; name?: string }
    | { type: "error"; detail: string; retryable: boolean };

export async function ask(
  messages: Array<{ role: string; content: string }>,
  onStep: (step: AssistantStep) => void,
  signal?: AbortSignal,
  page?: string,
  focus?: AssistantFocus
): Promise<void> {
  const headers = new Headers({ "Content-Type": "application/json", ...getAuthHeaders() });
  const response = await fetch(`${API_BASE}/api/assistant/stream`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      messages,
      page,
      account_id: focus?.account_id,
      job_id: focus?.job_id,
    }),
    signal,
  });
  if (!response.ok || !response.body) {
    throw new ApiError(response.status, `Запрос не прошёл (${response.status})`);
  }
  const reader = response.body.getReader();
  const decode = new TextDecoder();
  let pending = "";

  const applyLine = (line: string) => {
    const trimmed = line.trim();
    if (!trimmed.startsWith("data:")) return;
    try {
      onStep(JSON.parse(trimmed.slice(5)) as AssistantStep);
    } catch {
      /* one lost event is not the conversation */
    }
  };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    pending += decode.decode(value, { stream: true });
    const lines = pending.split("\n");
    pending = lines.pop() ?? "";
    for (const line of lines) applyLine(line);
  }
  pending += decode.decode();
  if (pending.trim()) applyLine(pending);
}
