import { describe, expect, it, vi } from "vitest";

import { ask } from "../assistant";

describe("assistant stream attachments", () => {
  it("sends attachments on user messages in the stream body", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      body: {
        getReader: () => ({
          read: async () => ({ done: true, value: undefined }),
        }),
      },
    });
    vi.stubGlobal("fetch", fetchMock);
    await ask(
      [
        {
          role: "user",
          content: "анимируй",
          attachments: [{ filename: "paste.png", media_type: "image", role: "start_image" }],
        },
      ],
      () => undefined
    );
    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    expect(body.messages[0].attachments[0].filename).toBe("paste.png");
    vi.unstubAllGlobals();
  });
});
