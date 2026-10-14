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
  gpu: { logs: vi.fn() },
}));

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
  useAuthMock.mockReturnValue({ role: "owner", state: "open" });
  apiMock.accounts.list.mockResolvedValue([{ username: "alice" }]);
  apiMock.videos.upload.mockResolvedValue({
    filename: "paste.png",
    media_type: "image",
    size_bytes: 100,
  });
  askMock.mockReset();
  askMock.mockResolvedValue(undefined);
  apiMock.gpu.logs.mockReset();
  apiMock.gpu.logs.mockResolvedValue({
    docker: [{ name: "reels-api", available: true, reason: "", lines: ["api ok"] }],
    gpu: { name: "gpu", available: true, reason: "", lines: ["ollama"] },
  });
});

describe("Assistant", () => {
  it("renders the prompt box", async () => {
    renderDock();
    expect(await screen.findByLabelText(/спросить агента/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^спросить$/i })).toBeInTheDocument();
  });

  it("opens docker and gpu logs from the corner", async () => {
    const user = userEvent.setup();
    renderDock();
    await user.click(await screen.findByRole("button", { name: "Логи" }));
    expect(await screen.findByRole("heading", { name: "Логи" })).toBeInTheDocument();
    expect(await screen.findByText("api ok")).toBeInTheDocument();
    expect(screen.getByText("ollama")).toBeInTheDocument();
    expect(screen.getByText("Видеокарта")).toBeInTheDocument();
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

  it("shows a live progress bar while the card starts", async () => {
    let release: (() => void) | undefined;
    askMock.mockImplementationOnce(
      (_messages, onStep) =>
        new Promise<void>((resolve) => {
          onStep({ type: "progress", text: "Качается образ на узел", detail: "deploying · 12 с", ratio: 0.3 });
          onStep({ type: "status", text: "Качается образ на узел" });
          onStep({ type: "progress", text: "Качается образ на узел", detail: "deploying · 40 с", ratio: 0.45 });
          release = () => {
            onStep({
              type: "done",
              reply: "готово",
              open_url: null,
              opened: null,
              used: [],
              images: [],
            });
            resolve();
          };
        })
    );
    const user = userEvent.setup();
    renderDock();
    await user.type(await screen.findByLabelText(/спросить агента/i), "привет");
    await user.click(screen.getByRole("button", { name: /^спросить$/i }));
    expect(await screen.findByRole("progressbar", { name: /качается образ/i })).toBeInTheDocument();
    expect(screen.getAllByText(/deploying · 40 с/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Качается образ на узел").length).toBeGreaterThanOrEqual(1);
    release?.();
    expect(await screen.findByText("готово")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("progressbar")).not.toBeInTheDocument());
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
});
