import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ask, type AssistantStep } from "../assistant";

const doneResult = {
  reply: "ок",
  open_url: null,
  opened: null,
  used: [],
  images: [],
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function runningJob(extra: Record<string, unknown> = {}) {
  return {
    id: 7,
    status: "running",
    actor: "owner",
    client_chat_id: "",
    prompt: "привет",
    reply: "",
    error: null,
    note: "",
    result: null,
    created_at: "2026-01-01T00:00:00",
    fresh: true,
    ...extra,
  };
}

let fetchSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  fetchSpy = vi.spyOn(window, "fetch");
});

afterEach(() => {
  fetchSpy.mockRestore();
});

describe("ask()", () => {
  it("posts to /api/assistant/jobs, not /run", async () => {
    fetchSpy
      .mockResolvedValueOnce(jsonResponse(runningJob()))
      .mockResolvedValueOnce(jsonResponse(runningJob({ status: "done", reply: "ок", result: doneResult })));
    await ask([{ role: "user", content: "привет" }], () => undefined);
    expect(fetchSpy).toHaveBeenCalledTimes(2);
    const url = String(fetchSpy.mock.calls[0][0]);
    expect(url).toContain("/api/assistant/jobs");
    expect(url).not.toContain("/api/assistant/run");
    expect(url).not.toContain("/api/assistant/stream");
    const body = JSON.parse(String(fetchSpy.mock.calls[0][1]?.body));
    expect(body.allow_browser).toBe(false);
  });

  it("sends allow_browser when options.allowBrowser is true", async () => {
    fetchSpy
      .mockResolvedValueOnce(jsonResponse(runningJob()))
      .mockResolvedValueOnce(jsonResponse(runningJob({ status: "done", reply: "ок", result: doneResult })));
    await ask([{ role: "user", content: "привет" }], () => undefined, undefined, undefined, undefined, {
      allowBrowser: true,
      clientChatId: "chat-1",
    });
    const body = JSON.parse(String(fetchSpy.mock.calls[0][1]?.body));
    expect(body.allow_browser).toBe(true);
    expect(body.client_chat_id).toBe("chat-1");
  });

  it("treats needs_user as a finished reply and stops polling", async () => {
    const steps: AssistantStep[] = [];
    fetchSpy
      .mockResolvedValueOnce(jsonResponse(runningJob()))
      .mockResolvedValueOnce(
        jsonResponse(
          runningJob({
            status: "needs_user",
            reply: "Нужен код входа",
            note: "Нужен код входа",
            result: { ...doneResult, reply: "Нужен код входа", asks: ["Какой код?"] },
          })
        )
      );
    await ask([{ role: "user", content: "войти" }], (step) => steps.push(step));
    expect(fetchSpy).toHaveBeenCalledTimes(2);
    const done = steps.find((step) => step.type === "done");
    expect(done).toMatchObject({ type: "done", reply: "Нужен код входа", asks: ["Какой код?"] });
  });

  it("emits the finished reply from the job snapshot", async () => {
    const steps: AssistantStep[] = [];
    fetchSpy
      .mockResolvedValueOnce(jsonResponse(runningJob()))
      .mockResolvedValueOnce(jsonResponse(runningJob({ status: "done", reply: "ок", result: doneResult })));
    await ask([{ role: "user", content: "привет" }], (step) => {
      steps.push(step);
    });
    expect(steps[0]).toMatchObject({ type: "done", reply: "ок", open_url: null, used: [], images: [] });
  });

  it("puts cards on the finished reply", async () => {
    const cards = [{ kind: "accounts", items: [{ id: 1, username: "bob", status: "active" }] }];
    const steps: AssistantStep[] = [];
    fetchSpy
      .mockResolvedValueOnce(jsonResponse(runningJob()))
      .mockResolvedValueOnce(
        jsonResponse(runningJob({ status: "done", reply: "ок", result: { ...doneResult, cards } }))
      );
    await ask([{ role: "user", content: "привет" }], (step) => {
      steps.push(step);
    });
    expect(steps).toHaveLength(1);
    expect(steps[0].type).toBe("done");
    if (steps[0].type === "done") expect(steps[0].cards).toEqual(cards);
  });
});
