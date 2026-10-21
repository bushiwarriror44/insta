import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../../context/ToastContext";
import { Assistant } from "../Assistant";
import { ask } from "../../api/assistant";

const useAuthMock = vi.hoisted(() => vi.fn());

const apiMock = vi.hoisted(() => ({
  accounts: { list: vi.fn() },
  videos: { upload: vi.fn() },
  factory: { getGeneration: vi.fn() },
  gpu: { logs: vi.fn(), status: vi.fn() },
  llmGateway: { credentials: vi.fn(), rotate: vi.fn(), setEnabled: vi.fn() },
}));

const gatewayFixture = {
  base_url: "http://localhost/llm/v1",
  api_key: "gw-test-key",
  mcp_url: "http://localhost/mcp",
  mcp_json: JSON.stringify(
    {
      mcpServers: {
        "reels-salad": {
          url: "http://localhost/mcp",
          headers: { Authorization: "Bearer gw-test-key" },
        },
      },
    },
    null,
    2
  ),
  model: "qwen3:8b",
  upstream_ok: true,
  enabled: true,
  recent: [] as Array<{
    at: string;
    channel: "llm" | "mcp";
    method: string;
    path: string;
    client_ip: string;
    user_agent: string;
    status: number;
  }>,
};

vi.mock("../../context/AuthContext", () => ({
  useAuth: useAuthMock,
}));

vi.mock("../../api/client", () => ({
  api: apiMock,
  formatApiError: (err: unknown) => String(err),
}));

vi.mock("../../api/assistant", () => ({
  ask: vi.fn(),
}));

const askMock = vi.mocked(ask);

function LocationProbe() {
  const loc = useLocation();
  return <div data-testid="loc">{`${loc.pathname}${loc.search}`}</div>;
}

function renderDock(ui = <Assistant />, path = "/") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ToastProvider>
        <LocationProbe />
        {ui}
      </ToastProvider>
    </MemoryRouter>
  );
}

beforeEach(() => {
  window.localStorage.clear();
  useAuthMock.mockReturnValue({ role: "owner", state: "open", authRequired: true });
  apiMock.accounts.list.mockResolvedValue([{ username: "alice" }]);
  apiMock.videos.upload.mockResolvedValue({
    filename: "paste.png",
    media_type: "image",
    size_bytes: 100,
  });
  askMock.mockReset();
  askMock.mockResolvedValue(undefined);
  apiMock.gpu.status.mockReset();
  apiMock.gpu.status.mockResolvedValue({
    configured: true,
    status: "stopped",
    billing: false,
    allocating_count: 0,
    creating_count: 0,
    running_count: 0,
    stopping_count: 0,
    chat_ok: false,
    wan_ok: null,
    detail: "",
    deploy_started_at: null,
  });
  apiMock.gpu.logs.mockReset();
  apiMock.gpu.logs.mockResolvedValue({
    docker: [{ name: "reels-api", available: true, reason: "", lines: ["api ok"] }],
    gpu: { name: "gpu", available: true, reason: "", lines: ["ollama"] },
  });
  apiMock.llmGateway.credentials.mockReset();
  apiMock.llmGateway.credentials.mockResolvedValue({ ...gatewayFixture, recent: [] });
  apiMock.llmGateway.rotate.mockReset();
  apiMock.llmGateway.rotate.mockResolvedValue({
    ...gatewayFixture,
    api_key: "gw-rotated",
    recent: [],
  });
  apiMock.llmGateway.setEnabled.mockReset();
  apiMock.llmGateway.setEnabled.mockImplementation(async (enabled: boolean) => ({
    ...gatewayFixture,
    enabled,
    recent: [],
  }));
});

describe("Assistant", () => {
  it("renders the prompt box", async () => {
    renderDock();
    expect(await screen.findByLabelText(/спросить агента/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^спросить$/i })).toBeInTheDocument();
  });

  it("shows the shared connect bar from gpu.status without a new message", async () => {
    apiMock.gpu.status.mockResolvedValue({
      configured: true,
      status: "deploying",
      billing: false,
      allocating_count: 0,
      creating_count: 1,
      running_count: 0,
      stopping_count: 0,
      chat_ok: false,
      wan_ok: null,
      detail: "",
      deploy_started_at: new Date(Date.now() - (47 * 60 + 12) * 1000).toISOString(),
      connect_phase: "pull",
      connect_label: "Качается образ на узел",
      connect_detail: "47 мин 12 с · работают 0, создаются 1, выделяются 0",
      connect_ratio: 0.45,
    });
    renderDock();
    expect(await screen.findByText("Качается образ на узел")).toBeInTheDocument();
    expect(screen.getByText(/47 мин 12 с/)).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: /качается образ/i })).toHaveAttribute(
      "aria-valuenow",
      "45"
    );
    expect(askMock).not.toHaveBeenCalled();
  });

  it("fills the shared connect bar when connect_phase is ready", async () => {
    apiMock.gpu.status.mockResolvedValue({
      configured: true,
      status: "running",
      billing: true,
      allocating_count: 0,
      creating_count: 0,
      running_count: 1,
      stopping_count: 0,
      chat_ok: true,
      wan_ok: null,
      detail: "",
      connect_phase: "ready",
      connect_label: "Чат отвечает",
      connect_detail: "работают 1, создаются 0, выделяются 0",
      connect_ratio: 1,
    });
    renderDock();
    expect(await screen.findByText("Чат отвечает")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: /чат отвечает/i })).toHaveAttribute(
      "aria-valuenow",
      "100"
    );
    expect(askMock).not.toHaveBeenCalled();
  });

  it("opens docker and gpu logs from the corner", async () => {
    const user = userEvent.setup();
    renderDock();
    await user.click(await screen.findByRole("button", { name: "Логи" }));
    expect(await screen.findByRole("heading", { name: "Логи" })).toBeInTheDocument();
    expect(await screen.findByText("api ok")).toBeInTheDocument();
    expect(screen.getByText("ollama")).toBeInTheDocument();
    expect(screen.getByText("Видеокарта")).toBeInTheDocument();
    expect(apiMock.gpu.logs).toHaveBeenCalledWith("1h");
    expect(screen.getByLabelText("Следить за хвостом")).toBeChecked();
    expect(screen.getByText(/Обновлено:/)).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Период логов"), "15m");
    await waitFor(() => expect(apiMock.gpu.logs).toHaveBeenCalledWith("15m"));
  });

  it("keeps requesting logs while the window stays open", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    const user = userEvent.setup();
    try {
      renderDock();
      await user.click(await screen.findByRole("button", { name: "Логи" }));
      await waitFor(() => expect(apiMock.gpu.logs).toHaveBeenCalledTimes(1));
      await act(async () => {
        vi.advanceTimersByTime(5000);
      });
      await waitFor(() => expect(apiMock.gpu.logs).toHaveBeenCalledTimes(2));
      expect(apiMock.gpu.logs).toHaveBeenLastCalledWith("1h");
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows Salad requests in a connection block", async () => {
    askMock.mockImplementationOnce(async (_messages, onStep) => {
      onStep({ type: "wire", text: "POST", name: "/organizations/acme/containers/insta/start", detail: "202" });
      onStep({
        type: "done",
        reply: "здесь",
        open_url: null,
        opened: null,
        used: [],
        images: [],
      });
    });
    const user = userEvent.setup();
    renderDock();
    await user.type(await screen.findByLabelText(/спросить агента/i), "привет");
    await user.click(screen.getByRole("button", { name: /^спросить$/i }));
    expect(await screen.findByText("здесь")).toBeInTheDocument();
    expect(screen.getByLabelText("Подключение")).toHaveTextContent("POST /organizations/acme/containers/insta/start → 202");
  });

  it("sends the current page in the request", async () => {
    const user = userEvent.setup();
    renderDock(<Assistant />, "/accounts");
    await user.type(await screen.findByLabelText(/спросить агента/i), "привет");
    await user.click(screen.getByRole("button", { name: /^спросить$/i }));
    await waitFor(() => expect(askMock).toHaveBeenCalled());
    expect(askMock.mock.calls[0][3]).toBe("/accounts");
  });

  it("sends the account id from the query string", async () => {
    const user = userEvent.setup();
    renderDock(<Assistant />, "/accounts?id=7");
    await user.type(await screen.findByLabelText(/спросить агента/i), "одобри");
    await user.click(screen.getByRole("button", { name: /^спросить$/i }));
    await waitFor(() => expect(askMock).toHaveBeenCalled());
    expect(askMock.mock.calls[0][4]).toEqual({ account_id: 7, job_id: undefined });
  });

  it("remembers the conversation", async () => {
    askMock.mockImplementation(async (_messages, onStep) => {
      onStep({
        type: "done",
        reply: "ок",
        open_url: null,
        opened: null,
        used: [],
        images: [],
      });
    });
    const user = userEvent.setup();
    const { unmount } = renderDock();
    await user.type(await screen.findByLabelText(/спросить агента/i), "привет");
    await user.click(screen.getByRole("button", { name: /^спросить$/i }));
    await waitFor(() => {
      const stored = JSON.parse(window.localStorage.getItem("assistant-dock:chats") || "{}");
      expect(stored.chats?.[0]?.messages?.length).toBeGreaterThan(0);
    });
    unmount();
    renderDock();
    expect(screen.getAllByText("привет").length).toBeGreaterThan(0);
  });

  it("keeps the warmup line above the reply", async () => {
    askMock.mockImplementation(async (_messages, onStep) => {
      onStep({ type: "status", text: "Запускаю видеокарту, подождите" });
      onStep({ type: "status", text: "Запускаю видеокарту, подождите" });
      onStep({ type: "status", text: "Прогреваю модель, подождите" });
      onStep({
        type: "done",
        reply: "я здесь",
        open_url: null,
        opened: null,
        used: [],
        images: [],
      });
    });
    const user = userEvent.setup();
    renderDock();
    await user.type(await screen.findByLabelText(/спросить агента/i), "привет");
    await user.click(screen.getByRole("button", { name: /^спросить$/i }));
    expect(await screen.findByText("я здесь")).toBeInTheDocument();
    expect(screen.getByText("Запускаю видеокарту, подождите")).toBeInTheDocument();
    expect(screen.getByText("Прогреваю модель, подождите")).toBeInTheDocument();
    expect(screen.getAllByText("Запускаю видеокарту, подождите")).toHaveLength(1);
  });

  it("keeps the shared connect bar when Salad is still deploying after an error", async () => {
    apiMock.gpu.status.mockResolvedValue({
      configured: true,
      status: "deploying",
      billing: false,
      allocating_count: 0,
      creating_count: 1,
      running_count: 0,
      stopping_count: 0,
      chat_ok: false,
      wan_ok: null,
      detail: "",
      connect_phase: "pull",
      connect_label: "Качается образ на узел",
      connect_detail: "deploying · 12 с",
      connect_ratio: 0.45,
    });
    askMock.mockImplementationOnce(async (_messages, onStep) => {
      onStep({
        type: "error",
        detail: "API Salad не отвечает, но группа может ещё качать образ",
        retryable: true,
      });
    });
    const user = userEvent.setup();
    renderDock();
    expect(await screen.findByRole("progressbar", { name: /качается образ/i })).toBeInTheDocument();
    await user.type(await screen.findByLabelText(/спросить агента/i), "привет");
    await user.click(screen.getByRole("button", { name: /^спросить$/i }));
    expect(await screen.findByText(/инстанс может ещё загружаться/i)).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: /качается образ/i })).toBeInTheDocument();
    expect(screen.getAllByText("Качается образ на узел").length).toBeGreaterThanOrEqual(1);
  });

  it("does not pretend the image is downloading when Start was not sent", async () => {
    askMock.mockImplementationOnce(async (_messages, onStep) => {
      onStep({ type: "progress", text: "Отправляю Start в Salad…", detail: "попытка 2", ratio: 0.2 });
      onStep({
        type: "error",
        detail: "Не удалось отправить Start в Salad, группа осталась остановленной.",
        retryable: true,
      });
    });
    const user = userEvent.setup();
    renderDock();
    await user.type(await screen.findByLabelText(/спросить агента/i), "привет");
    await user.click(screen.getByRole("button", { name: /^спросить$/i }));
    expect(await screen.findByText(/осталась остановленной/i)).toBeInTheDocument();
    expect(screen.queryByText(/инстанс может ещё загружаться/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("asks for clarifications and sends them as the next message", async () => {
    askMock.mockImplementationOnce(async (_messages, onStep) => {
      onStep({ type: "ask", questions: ["какой username?"], text: "нужен логин" });
      onStep({
        type: "done",
        reply: "Нужны уточнения, чтобы продолжить.",
        open_url: null,
        opened: null,
        used: ["ask_operator"],
        images: [],
        asks: ["какой username?"],
      });
    });
    const user = userEvent.setup();
    renderDock();
    await user.type(await screen.findByLabelText(/спросить агента/i), "добавь аккаунт");
    await user.click(screen.getByRole("button", { name: /^спросить$/i }));
    const field = await screen.findByLabelText("какой username?");
    await user.type(field, "alice");
    await user.click(screen.getByRole("button", { name: /^ответить$/i }));
    await waitFor(() => expect(askMock).toHaveBeenCalledTimes(2));
    const followUp = askMock.mock.calls[1][0] as Array<{ role: string; content: string }>;
    expect(followUp.at(-1)?.content).toContain("Уточнения:");
    expect(followUp.at(-1)?.content).toContain("alice");
  });

  it("renders a setup form from ask fields and sends field ids", async () => {
    askMock.mockImplementationOnce(async (_messages, onStep) => {
      onStep({
        type: "ask",
        text: "заполните форму",
        questions: ["Метка прокси", "Username"],
        fields: [
          { id: "proxy_label", label: "Метка прокси", kind: "text" },
          { id: "username", label: "Username", kind: "text" },
          {
            id: "platform",
            label: "Площадка",
            kind: "select",
            options: ["instagram", "youtube", "tiktok"],
          },
          { id: "password", label: "Пароль", kind: "password" },
        ],
      });
      onStep({
        type: "done",
        reply: "Нужны уточнения, чтобы продолжить.",
        open_url: null,
        opened: null,
        used: ["ask_operator"],
        images: [],
        asks: ["Метка прокси", "Username"],
      });
    });
    const user = userEvent.setup();
    renderDock();
    await user.type(await screen.findByLabelText(/спросить агента/i), "форма");
    await user.click(screen.getByRole("button", { name: /^спросить$/i }));
    await user.type(await screen.findByLabelText("Метка прокси"), "res-1");
    await user.type(screen.getByLabelText("Username"), "alice");
    await user.selectOptions(screen.getByLabelText("Площадка"), "instagram");
    await user.type(screen.getByLabelText("Пароль"), "secret");
    await user.click(screen.getByRole("button", { name: /^ответить$/i }));
    await waitFor(() => expect(askMock).toHaveBeenCalledTimes(2));
    const followUp = askMock.mock.calls[1][0] as Array<{ role: string; content: string }>;
    const body = followUp.at(-1)?.content ?? "";
    expect(body).toContain("Уточнения:");
    expect(body).toContain("proxy_label: res-1");
    expect(body).toContain("username: alice");
    expect(body).toContain("platform: instagram");
    expect(body).toContain("password: secret");
  });

  it("opens the proxy setup form from the plus menu", async () => {
    const user = userEvent.setup();
    renderDock();
    await user.click(await screen.findByRole("button", { name: /^ещё$/i }));
    await user.click(await screen.findByRole("menuitem", { name: /форма прокси/i }));
    expect(await screen.findByLabelText(/url \(http/i)).toBeInTheDocument();
    expect(screen.getByText(/необязательно/i)).toBeInTheDocument();
  });

  it("allows optional ask fields to stay empty", async () => {
    askMock.mockImplementationOnce(async (_messages, onStep) => {
      onStep({
        type: "ask",
        questions: ["данные"],
        fields: [
          { id: "label", label: "Метка прокси", kind: "text", required: true },
          {
            id: "url",
            label: "URL (http://user:pass@host:port)",
            kind: "password",
            required: true,
          },
          { id: "country", label: "Страна", kind: "text", required: false },
        ],
      });
      onStep({
        type: "done",
        reply: "Нужны уточнения.",
        open_url: null,
        opened: null,
        used: ["create_proxies"],
        images: [],
        asks: ["данные"],
        fields: [
          { id: "label", label: "Метка прокси", kind: "text", required: true },
          {
            id: "url",
            label: "URL (http://user:pass@host:port)",
            kind: "password",
            required: true,
          },
          { id: "country", label: "Страна", kind: "text", required: false },
        ],
      });
    });
    const user = userEvent.setup();
    renderDock();
    await user.type(await screen.findByLabelText(/спросить агента/i), "прокси");
    await user.click(screen.getByRole("button", { name: /^спросить$/i }));
    await user.type(await screen.findByLabelText("Метка прокси"), "px-1");
    await user.type(screen.getByLabelText(/url \(http/i), "http://u:p@h:1");
    await user.click(await screen.findByRole("button", { name: /^ответить$/i }));
    await waitFor(() => expect(askMock).toHaveBeenCalledTimes(2));
    const body = (askMock.mock.calls[1][0] as Array<{ content: string }>).at(-1)?.content ?? "";
    expect(body).not.toContain("country:");
  });

  it("spins a sparkle while the agent is working", async () => {
    let release!: () => void;
    askMock.mockImplementation(
      () =>
        new Promise((resolve) => {
          release = () => resolve();
        })
    );
    const user = userEvent.setup();
    renderDock();
    await user.type(await screen.findByLabelText(/спросить агента/i), "привет");
    await user.click(screen.getByRole("button", { name: /^спросить$/i }));
    expect((await screen.findAllByTestId("assistant-sparkle")).length).toBeGreaterThan(0);
    expect(screen.getByRole("status")).toBeInTheDocument();
    release();
    await waitFor(() => expect(screen.queryByTestId("assistant-sparkle")).not.toBeInTheDocument());
  });

  it("hides the dock and remembers it", async () => {
    const onHiddenChange = vi.fn();
    const user = userEvent.setup();
    const { unmount } = renderDock(<Assistant onHiddenChange={onHiddenChange} />);
    await user.click(await screen.findByRole("button", { name: /^скрыть$/i }));
    expect(screen.getByRole("button", { name: /показать агента/i })).toBeInTheDocument();
    expect(screen.queryByLabelText(/спросить агента/i)).not.toBeInTheDocument();
    expect(onHiddenChange).toHaveBeenCalledWith(true);
    expect(window.localStorage.getItem("assistant-dock:hidden")).toBe("1");
    unmount();
    renderDock(<Assistant onHiddenChange={onHiddenChange} />);
    expect(screen.getByRole("button", { name: /показать агента/i })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /показать агента/i }));
    expect(await screen.findByLabelText(/спросить агента/i)).toBeInTheDocument();
    expect(window.localStorage.getItem("assistant-dock:hidden")).toBe("0");
  });

  it("refreshes lists after a successful create", async () => {
    const onMutate = vi.fn();
    window.addEventListener("assistant-mutate", onMutate);
    askMock.mockImplementation(async (_messages, onStep) => {
      onStep({
        type: "done",
        reply: "добавил аккаунт",
        open_url: null,
        opened: null,
        used: ["create_account"],
        images: [],
        created: { accounts: [10], proxies: [] },
      });
    });
    const user = userEvent.setup();
    renderDock();
    await user.type(await screen.findByLabelText(/спросить агента/i), "создай");
    await user.click(screen.getByRole("button", { name: /^спросить$/i }));
    await waitFor(() => expect(onMutate).toHaveBeenCalled());
    const event = onMutate.mock.calls[0][0] as CustomEvent;
    expect(event.detail).toEqual({ accounts: [10], proxies: [] });
    window.removeEventListener("assistant-mutate", onMutate);
  });

  it("shows tool calls and tokens while streaming", async () => {
    let release!: () => void;
    askMock.mockImplementation(async (_messages, onStep) => {
      onStep({ type: "tool", text: "смотрю аккаунты" });
      onStep({ type: "token", text: "сейчас" });
      await new Promise<void>((resolve) => {
        release = resolve;
      });
    });
    const user = userEvent.setup();
    renderDock();
    await user.type(await screen.findByLabelText(/спросить агента/i), "что есть");
    await user.click(screen.getByRole("button", { name: /^спросить$/i }));
    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent(/смотрю аккаунты/i);
    expect(status).toHaveTextContent(/пишет/i);
    release();
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
  });

  it("shows a tool hint while a named tool is running", async () => {
    let release!: () => void;
    askMock.mockImplementation(async (_messages, onStep) => {
      onStep({ type: "tool", text: "ставлю план", name: "plan_account" });
      await new Promise<void>((resolve) => {
        release = resolve;
      });
    });
    const user = userEvent.setup();
    renderDock();
    await user.type(await screen.findByLabelText(/спросить агента/i), "поставь план");
    await user.click(screen.getByRole("button", { name: /^спросить$/i }));
    expect(await screen.findByTestId("assistant-tool-hint")).toHaveTextContent(/planjob/i);
    expect(screen.queryByTestId("assistant-page-hint")).not.toBeInTheDocument();
    release();
    await waitFor(() => expect(screen.queryByTestId("assistant-tool-hint")).not.toBeInTheDocument());
  });

  it("shows a page hint on /agent", async () => {
    renderDock(<Assistant />, "/agent");
    expect(await screen.findByTestId("assistant-page-hint")).toHaveTextContent(/план роликов/i);
  });

  it("opens the chat manual", async () => {
    const user = userEvent.setup();
    renderDock();
    await user.click(await screen.findByRole("button", { name: /^ещё$/i }));
    await user.click(screen.getByRole("menuitem", { name: /^мануал$/i }));
    expect(screen.getByTestId("assistant-manual")).toHaveTextContent(/sqlite/i);
    expect(screen.getByText(/start_browser из нижнего чата/i)).toBeInTheDocument();
  });

  it("sends a preset prompt from the examples list", async () => {
    const user = userEvent.setup();
    renderDock();
    await user.click(await screen.findByRole("button", { name: /^ещё$/i }));
    await user.click(screen.getByRole("menuitem", { name: /что можно спросить/i }));
    await user.click(screen.getByRole("button", { name: /^открой аккаунты$/i }));
    await waitFor(() => expect(askMock).toHaveBeenCalled());
    const messages = askMock.mock.calls[0][0] as Array<{ role: string; content: string }>;
    expect(messages.at(-1)?.content).toBe("открой аккаунты");
  });

  it("navigates in-place when the reply has open_url with ?id=", async () => {
    askMock.mockImplementation(async (_messages, onStep) => {
      onStep({
        type: "done",
        reply: "открыл",
        open_url: "/accounts?id=7",
        opened: "alice",
        used: ["open_account"],
        images: [],
      });
    });
    const user = userEvent.setup();
    renderDock();
    await user.type(await screen.findByLabelText(/спросить агента/i), "открой аккаунт");
    await user.click(screen.getByRole("button", { name: /^спросить$/i }));
    await waitFor(() => expect(screen.getByTestId("loc")).toHaveTextContent("/accounts?id=7"));
  });

  it("shows a stop_worker confirmation as clarifications", async () => {
    askMock.mockImplementation(async (_messages, onStep) => {
      onStep({ type: "ask", questions: ["Остановить воркер?"], text: "публикации перестанут ехать" });
      onStep({
        type: "done",
        reply: "Нужны уточнения, чтобы продолжить.",
        open_url: null,
        opened: null,
        used: ["stop_worker"],
        images: [],
        asks: ["Остановить воркер?"],
      });
    });
    const user = userEvent.setup();
    renderDock();
    await user.type(await screen.findByLabelText(/спросить агента/i), "останови воркер");
    await user.click(screen.getByRole("button", { name: /^спросить$/i }));
    expect(await screen.findByLabelText("Остановить воркер?")).toBeInTheDocument();
    expect(screen.getAllByText(/нужны уточнения/i).length).toBeGreaterThan(0);
  });

  it("keeps printed text when the stream errors", async () => {
    askMock.mockImplementation(async (_messages, onStep) => {
      onStep({ type: "tool", text: "посмотрел аккаунты", name: "list_accounts" });
      onStep({ type: "token", text: "уже напечатано" });
      onStep({ type: "error", detail: "шлюз Salad оборвал ответ", retryable: true });
    });
    const user = userEvent.setup();
    renderDock();
    await user.type(await screen.findByLabelText(/спросить агента/i), "привет");
    await user.click(screen.getByRole("button", { name: /^спросить$/i }));
    expect(await screen.findByText("уже напечатано")).toBeInTheDocument();
    expect(screen.getByText("Ответ оборвался на шлюзе.")).toBeInTheDocument();
    expect(screen.getByText("посмотрел аккаунты")).toBeInTheDocument();
    expect(screen.queryByText("шлюз Salad оборвал ответ")).not.toBeInTheDocument();
  });

  it("replaces a media-type phrase with the Russian sentence", async () => {
    askMock.mockImplementation(async (_messages, onStep) => {
      onStep({ type: "token", text: "Unsupported" });
      onStep({ type: "token", text: " Media Type" });
      onStep({
        type: "error",
        detail: "хост модели отклонил формат запроса. Напишите ещё раз.",
        retryable: true,
      });
    });
    const user = userEvent.setup();
    renderDock();
    await user.type(await screen.findByLabelText(/спросить агента/i), "привет");
    await user.click(screen.getByRole("button", { name: /^спросить$/i }));
    expect(await screen.findByText(/формат запроса/i)).toBeInTheDocument();
    expect(screen.queryByText(/unsupported media type/i)).not.toBeInTheDocument();
  });

  it("keeps printed text when the connection drops", async () => {
    askMock.mockImplementation(async (_messages, onStep) => {
      onStep({ type: "token", text: "кусок ответа" });
      throw new Error("network");
    });
    const user = userEvent.setup();
    renderDock();
    await user.type(await screen.findByLabelText(/спросить агента/i), "привет");
    await user.click(screen.getByRole("button", { name: /^спросить$/i }));
    expect(await screen.findByText("кусок ответа")).toBeInTheDocument();
    expect(screen.getByText("Ответ оборвался на шлюзе.")).toBeInTheDocument();
    expect(screen.queryByText(/network/i)).not.toBeInTheDocument();
  });

  it("shows reasoning above the answer and collapses it once the answer starts", async () => {
    let release: (() => void) | undefined;
    askMock.mockImplementation(
      (_messages, onStep) =>
        new Promise<void>((resolve) => {
          onStep({ type: "think", text: "сначала проверяю панель" });
          release = () => {
            onStep({ type: "token", text: "готово" });
            onStep({
              type: "done",
              reply: "готово",
              open_url: null,
              opened: null,
              used: [],
              images: [],
              thinking: "сначала проверяю панель",
            });
            resolve();
          };
        })
    );
    const user = userEvent.setup();
    renderDock();
    await user.type(await screen.findByLabelText(/спросить агента/i), "привет");
    await user.click(screen.getByRole("button", { name: /^спросить$/i }));
    const summary = await screen.findByText("Рассуждение");
    expect(summary.closest("details")).toHaveAttribute("open");
    expect(screen.getByText("сначала проверяю панель")).toBeInTheDocument();
    release?.();
    await waitFor(() => {
      expect(screen.getAllByText("Рассуждение")).toHaveLength(1);
      expect(screen.getByText("Рассуждение").closest("details")).not.toHaveAttribute("open");
    });
    await user.click(screen.getByText("Рассуждение"));
    expect(screen.getByText("Рассуждение").closest("details")).toHaveAttribute("open");
  });

  it("keeps a live reasoning block open and appends the next chunk", async () => {
    let release: (() => void) | undefined;
    askMock.mockImplementationOnce(
      (_messages, onStep) =>
        new Promise<void>((resolve) => {
          onStep({ type: "think", text: "проверяю воркер" });
          onStep({ type: "think", text: " и логи" });
          release = () => {
            onStep({
              type: "done",
              reply: "воркер запущен",
              open_url: null,
              opened: null,
              used: [],
              images: [],
              thinking: "проверяю воркер и логи",
            });
            resolve();
          };
        })
    );
    const user = userEvent.setup();
    renderDock();
    await user.type(await screen.findByLabelText(/спросить агента/i), "привет");
    await user.click(screen.getByRole("button", { name: /^спросить$/i }));
    const summary = await screen.findByText("Рассуждение");
    expect(summary.closest("details")).toHaveAttribute("open");
    expect(screen.getByText("проверяю воркер и логи")).toBeInTheDocument();
    expect(summary.closest("details")?.querySelector("p")?.className).toMatch(/max-h-64/);
    release?.();
    expect(await screen.findByText("воркер запущен")).toBeInTheDocument();
  });

  it("keeps two chats apart and renames the active one", async () => {
    askMock.mockImplementation(async (messages, onStep) => {
      const last = (messages as Array<{ content: string }>).at(-1)?.content ?? "";
      onStep({
        type: "done",
        reply: `ответ:${last}`,
        open_url: null,
        opened: null,
        used: [],
        images: [],
      });
    });
    const user = userEvent.setup();
    renderDock();
    await user.type(await screen.findByLabelText(/спросить агента/i), "первый");
    await user.click(screen.getByRole("button", { name: /^спросить$/i }));
    expect(await screen.findByText("ответ:первый")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^новый$/i }));
    await user.type(screen.getByLabelText(/спросить агента/i), "второй");
    await user.click(screen.getByRole("button", { name: /^спросить$/i }));
    expect(await screen.findByText("ответ:второй")).toBeInTheDocument();
    expect(screen.queryByText("ответ:первый")).not.toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: /^первый/ }));
    expect(await screen.findByText("ответ:первый")).toBeInTheDocument();
    expect(screen.queryByText("ответ:второй")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /переименовать чат/i }));
    const field = screen.getByLabelText("Название чата");
    await user.clear(field);
    await user.type(field, "Рабочий{Enter}");
    expect(await screen.findByRole("tab", { name: /^Рабочий/ })).toBeInTheDocument();
  });

  it("deletes the active chat and keeps the other", async () => {
    askMock.mockImplementation(async (messages, onStep) => {
      const last = (messages as Array<{ content: string }>).at(-1)?.content ?? "";
      onStep({
        type: "done",
        reply: `ответ:${last}`,
        open_url: null,
        opened: null,
        used: [],
        images: [],
      });
    });
    const user = userEvent.setup();
    renderDock();
    await user.type(await screen.findByLabelText(/спросить агента/i), "первый");
    await user.click(screen.getByRole("button", { name: /^спросить$/i }));
    expect(await screen.findByText("ответ:первый")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^новый$/i }));
    await user.type(screen.getByLabelText(/спросить агента/i), "второй");
    await user.click(screen.getByRole("button", { name: /^спросить$/i }));
    expect(await screen.findByText("ответ:второй")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^удалить чат$/i }));
    expect(screen.queryByRole("tab", { name: /^второй/ })).not.toBeInTheDocument();
    expect(screen.queryByText("ответ:второй")).not.toBeInTheDocument();
    expect(await screen.findByText("ответ:первый")).toBeInTheDocument();
    await waitFor(() => {
      const stored = JSON.parse(window.localStorage.getItem("assistant-dock:chats") || "{}");
      const titles = (stored.chats ?? []).map((item: { title: string }) => item.title);
      expect(titles).toEqual(["первый"]);
    });
  });

  it("replaces the only chat with an empty one", async () => {
    askMock.mockImplementation(async (_messages, onStep) => {
      onStep({
        type: "done",
        reply: "один ответ",
        open_url: null,
        opened: null,
        used: [],
        images: [],
      });
    });
    const user = userEvent.setup();
    renderDock();
    await user.type(await screen.findByLabelText(/спросить агента/i), "один");
    await user.click(screen.getByRole("button", { name: /^спросить$/i }));
    expect(await screen.findByText("один ответ")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^удалить чат$/i }));
    expect(screen.queryByText("один ответ")).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /^Новый чат$/ })).toBeInTheDocument();
    await waitFor(() => {
      const stored = JSON.parse(window.localStorage.getItem("assistant-dock:chats") || "{}");
      expect(stored.chats).toHaveLength(1);
      expect(stored.chats[0].title).toBe("Новый чат");
      expect(stored.chats[0].messages).toEqual([]);
    });
  });

  it("clears the active chat while it is answering and leaves the other", async () => {
    let release: (() => void) | undefined;
    askMock.mockImplementationOnce(
      () =>
        new Promise<void>((resolve) => {
          release = () => resolve();
        })
    );
    const user = userEvent.setup();
    renderDock();
    await user.type(await screen.findByLabelText(/спросить агента/i), "долго");
    await user.click(screen.getByRole("button", { name: /^спросить$/i }));
    expect(await screen.findByRole("tab", { name: /^долго/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^новый$/i }));
    askMock.mockImplementationOnce(async (_messages, onStep) => {
      onStep({
        type: "done",
        reply: "второй ответ",
        open_url: null,
        opened: null,
        used: [],
        images: [],
      });
    });
    await user.type(screen.getByLabelText(/спросить агента/i), "ещё");
    await user.click(screen.getByRole("button", { name: /^спросить$/i }));
    expect(await screen.findByText("второй ответ")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: /^долго/ }));
    await user.click(screen.getByRole("button", { name: /^ещё$/i }));
    await user.click(screen.getByRole("menuitem", { name: /^очистить$/i }));
    expect(screen.queryByText("долго")).not.toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: /^ещё/ }));
    expect(screen.getByText("второй ответ")).toBeInTheDocument();
    release?.();
  });

  it("uploads a pasted image into the draft reference strip", async () => {
    const uploadMock = apiMock.videos.upload;
    renderDock();
    const box = await screen.findByLabelText(/спросить агента/i);
    const file = new File([new Uint8Array([1, 2, 3])], "shot.png", { type: "image/png" });
    await act(async () => {
      fireEvent.paste(box, {
        clipboardData: {
          files: [file],
          items: [],
        },
      });
    });
    await waitFor(() => expect(uploadMock).toHaveBeenCalled());
  });

  it("shows render progress when generation events arrive", async () => {
    const user = userEvent.setup();
    askMock.mockImplementation(async (_messages, onStep) => {
      onStep({ type: "generation", text: "running", name: "42", detail: "backend=auto|stage=encoding" });
      onStep({
        type: "done",
        reply: "жду",
        open_url: null,
        opened: null,
        used: ["wait_render"],
        images: [],
      });
    });
    renderDock();
    await user.type(await screen.findByLabelText(/спросить агента/i), "рендер");
    await user.click(screen.getByRole("button", { name: /^спросить$/i }));
    expect(await screen.findByTestId("render-progress-card")).toBeInTheDocument();
    expect(screen.getByText(/рендер #42/i)).toBeInTheDocument();
  });

  it("opens a saved single thread as the first chat", async () => {
    window.localStorage.setItem(
      "assistant-dock:thread",
      JSON.stringify([{ role: "user", content: "старый разговор" }])
    );
    renderDock();
    expect(screen.getAllByText("старый разговор").length).toBeGreaterThan(0);
  });

  it("switches to API and MCP tabs with copyable credentials", async () => {
    const user = userEvent.setup();
    renderDock();
    expect(await screen.findByTestId("assistant-dock-tab-agent")).toBeInTheDocument();
    await user.click(screen.getByTestId("assistant-dock-tab-api"));
    expect(await screen.findByTestId("assistant-api-panel")).toBeInTheDocument();
    await waitFor(() => expect(apiMock.llmGateway.credentials).toHaveBeenCalled());
    expect(screen.getByLabelText("Base URL")).toHaveValue(gatewayFixture.base_url);
    expect(screen.getByLabelText("API Key")).toHaveValue(gatewayFixture.api_key);
    expect(screen.getByText(/шлюз доступен/i)).toBeInTheDocument();
    expect(screen.getByTestId("assistant-gateway-recent-empty")).toBeInTheDocument();

    await user.click(screen.getByTestId("assistant-dock-tab-mcp"));
    expect(await screen.findByTestId("assistant-mcp-panel")).toBeInTheDocument();
    expect(screen.getByLabelText("MCP JSON")).toHaveValue(gatewayFixture.mcp_json);
  });

  it("toggles gateway off and regenerates key after confirm", async () => {
    const user = userEvent.setup();
    apiMock.llmGateway.credentials.mockResolvedValue({
      ...gatewayFixture,
      recent: [
        {
          at: "2026-05-01T12:00:00Z",
          channel: "llm",
          method: "GET",
          path: "/llm/v1/models",
          client_ip: "127.0.0.1",
          user_agent: "cursor",
          status: 502,
          detail: "Не удалось достучаться до модели (AGENT_BASE_URL).",
        },
      ],
    });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderDock();
    await user.click(await screen.findByTestId("assistant-dock-tab-api"));
    expect(await screen.findByTestId("assistant-gateway-recent")).toBeInTheDocument();
    expect(screen.getByText(/\/llm\/v1\/models/)).toBeInTheDocument();
    expect(screen.getByText(/AGENT_BASE_URL/)).toBeInTheDocument();

    await user.click(screen.getByLabelText("Шлюз включён"));
    await waitFor(() => expect(apiMock.llmGateway.setEnabled).toHaveBeenCalledWith(false));
    expect(await screen.findByText(/выключен/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /перегенерировать ключ/i }));
    expect(confirmSpy).toHaveBeenCalled();
    await waitFor(() => expect(apiMock.llmGateway.rotate).toHaveBeenCalled());
    expect(screen.getByLabelText("API Key")).toHaveValue("gw-rotated");
    confirmSpy.mockRestore();
  });

  it("hides gateway tabs for operators", async () => {
    useAuthMock.mockReturnValue({ role: "operator", state: "authed", authRequired: true });
    renderDock();
    expect(await screen.findByLabelText(/спросить агента/i)).toBeInTheDocument();
    expect(screen.queryByTestId("assistant-dock-tab-api")).not.toBeInTheDocument();
    expect(screen.queryByTestId("assistant-dock-tab-mcp")).not.toBeInTheDocument();
  });
});
