import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ask, type AssistantStep } from "../assistant";

function sseStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  let i = 0;
  return new ReadableStream({
    pull(controller) {
      if (i < chunks.length) {
        controller.enqueue(encoder.encode(chunks[i++]));
        return;
      }
      controller.close();
    },
  });
}

const doneEvent = {
  type: "done" as const,
  reply: "ок",
  open_url: null,
  opened: null,
  used: [],
  images: [],
};

let fetchSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  fetchSpy = vi.spyOn(window, "fetch");
});

afterEach(() => {
  fetchSpy.mockRestore();
});

describe("ask()", () => {
  it("posts to /api/assistant/stream, not /run", async () => {
    fetchSpy.mockResolvedValue(
      new Response(sseStream([`data: ${JSON.stringify(doneEvent)}\n\n`]), {
        status: 200,
        headers: { "content-type": "text/event-stream" },
      })
    );
    await ask([{ role: "user", content: "привет" }], () => undefined);
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const url = String(fetchSpy.mock.calls[0][0]);
    expect(url).toContain("/api/assistant/stream");
    expect(url).not.toContain("/api/assistant/run");
    const body = JSON.parse(String(fetchSpy.mock.calls[0][1]?.body));
    expect(body.allow_browser).toBe(false);
  });

  it("sends allow_browser when options.allowBrowser is true", async () => {
    fetchSpy.mockResolvedValue(
      new Response(sseStream([`data: ${JSON.stringify(doneEvent)}\n\n`]), {
        status: 200,
        headers: { "content-type": "text/event-stream" },
      })
    );
    await ask([{ role: "user", content: "привет" }], () => undefined, undefined, undefined, undefined, {
      allowBrowser: true,
    });
    const body = JSON.parse(String(fetchSpy.mock.calls[0][1]?.body));
    expect(body.allow_browser).toBe(true);
  });

  it("flushes a trailing data line without a newline", async () => {
    const steps: AssistantStep[] = [];
    fetchSpy.mockResolvedValue(
      new Response(sseStream([`data: ${JSON.stringify(doneEvent)}`]), {
        status: 200,
        headers: { "content-type": "text/event-stream" },
      })
    );
    await ask([{ role: "user", content: "привет" }], (step) => {
      steps.push(step);
    });
    expect(steps).toEqual([doneEvent]);
  });
});
