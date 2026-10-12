import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../../context/ToastContext";
import { Renders } from "../Renders";

const queuedGen = {
  id: 9,
  status: "queued",
  prompt: "fog",
  stage: "",
  post_title: "Ridge",
  last_error: null,
  cost_usd: 0.05,
};

const failedGen = {
  ...queuedGen,
  id: 11,
  status: "failed",
  post_title: "Storm",
  last_error: "pollinations rejected — Локальный рендер: WAN_BASE_URL",
};

const account = { id: 1, username: "alice" };

const apiMock = vi.hoisted(() => ({
  accounts: { list: vi.fn() },
  videos: { list: vi.fn() },
  factory: {
    generations: vi.fn(),
    backends: vi.fn(),
    compositions: vi.fn(),
    createGeneration: vi.fn(),
    cancelGeneration: vi.fn(),
    retryGeneration: vi.fn(),
    createComposition: vi.fn(),
    cancelComposition: vi.fn(),
    retryComposition: vi.fn(),
  },
}));

vi.mock("../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../api/client")>(
    "../../api/client"
  );
  return {
    ...actual,
    api: apiMock,
  };
});

function defaults() {
  apiMock.accounts.list.mockResolvedValue([]);
  apiMock.videos.list.mockResolvedValue([]);
  apiMock.factory.generations.mockResolvedValue([queuedGen]);
  apiMock.factory.backends.mockResolvedValue([
    { name: "auto", healthy: true, licence: "depends", experimental: false, detail: "fal: ok" },
    { name: "fal", healthy: true, licence: "Apache-2.0", experimental: false, detail: "" },
  ]);
  apiMock.factory.compositions.mockResolvedValue([]);
  apiMock.factory.createGeneration.mockResolvedValue({ id: 9 });
  apiMock.factory.cancelGeneration.mockResolvedValue({ id: 9 });
  apiMock.factory.retryGeneration.mockResolvedValue({ id: 11 });
  apiMock.factory.createComposition.mockResolvedValue({ id: 3 });
  apiMock.factory.cancelComposition.mockResolvedValue({ id: 4 });
  apiMock.factory.retryComposition.mockResolvedValue({ id: 4 });
}

function renderRenders(initialEntry = "/renders") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <ToastProvider>
        <Renders />
      </ToastProvider>
    </MemoryRouter>
  );
}

describe("Renders page", () => {
  beforeEach(() => {
    Object.values(apiMock.accounts).forEach((fn) => fn.mockReset());
    Object.values(apiMock.videos).forEach((fn) => fn.mockReset());
    Object.values(apiMock.factory).forEach((fn) => fn.mockReset());
    defaults();
  });

  it("lists fal jobs", async () => {
    renderRenders();
    expect(await screen.findByRole("heading", { name: /рендеры и склейки/i })).toBeInTheDocument();
    expect(await screen.findByText("Ridge")).toBeInTheDocument();
  });

  it("queues a render without an account and links the toast to /renders?gen=", async () => {
    renderRenders();
    await screen.findByText("Ridge");
    fireEvent.change(screen.getByPlaceholderText("Промпт"), { target: { value: "fog over ridge" } });
    fireEvent.click(screen.getByRole("button", { name: /поставить рендер/i }));
    await waitFor(() =>
      expect(apiMock.factory.createGeneration).toHaveBeenCalledWith({
        prompt: "fog over ridge",
        backend: "auto",
        account_id: undefined,
      })
    );
    const open = await screen.findByRole("link", { name: /открыть/i });
    expect(open).toHaveAttribute("href", "/renders?gen=9");
  });

  it("highlights the generation from the URL", async () => {
    renderRenders("/renders?gen=9");
    const title = await screen.findByText("Ridge");
    expect(title.closest("tr")).toHaveClass("bg-brand-600/10");
  });

  it("queues a render with the selected account", async () => {
    apiMock.accounts.list.mockResolvedValue([account]);
    renderRenders();
    await screen.findByText("Ridge");
    fireEvent.change(screen.getByRole("combobox", { name: /аккаунт/i }), { target: { value: "1" } });
    fireEvent.change(screen.getByPlaceholderText("Промпт"), { target: { value: "city night" } });
    fireEvent.click(screen.getByRole("button", { name: /поставить рендер/i }));
    await waitFor(() =>
      expect(apiMock.factory.createGeneration).toHaveBeenCalledWith({
        prompt: "city night",
        backend: "auto",
        account_id: 1,
      })
    );
  });

  it("queues a render with an explicit backend", async () => {
    renderRenders();
    await screen.findByText("Ridge");
    fireEvent.change(screen.getByRole("combobox", { name: /бэкенд/i }), { target: { value: "fal" } });
    fireEvent.change(screen.getByPlaceholderText("Промпт"), { target: { value: "only fal" } });
    fireEvent.click(screen.getByRole("button", { name: /поставить рендер/i }));
    await waitFor(() =>
      expect(apiMock.factory.createGeneration).toHaveBeenCalledWith({
        prompt: "only fal",
        backend: "fal",
        account_id: undefined,
      })
    );
  });

  it("queues a render after clicking a backend chip", async () => {
    renderRenders();
    await screen.findByText("Ridge");
    fireEvent.click(screen.getByRole("button", { name: /fal/i }));
    fireEvent.change(screen.getByPlaceholderText("Промпт"), { target: { value: "from chip" } });
    fireEvent.click(screen.getByRole("button", { name: /поставить рендер/i }));
    await waitFor(() =>
      expect(apiMock.factory.createGeneration).toHaveBeenCalledWith({
        prompt: "from chip",
        backend: "fal",
        account_id: undefined,
      })
    );
  });

  it("queues a join from clip ids and links the toast to /renders?join=", async () => {
    renderRenders();
    await screen.findByText("Ridge");
    fireEvent.change(screen.getByPlaceholderText(/id клипов/i), { target: { value: "12, 15" } });
    fireEvent.click(screen.getByRole("button", { name: /склеить/i }));
    await waitFor(() =>
      expect(apiMock.factory.createComposition).toHaveBeenCalledWith({
        clip_ids: [12, 15],
        account_id: undefined,
      })
    );
    const open = await screen.findByRole("link", { name: /открыть/i });
    expect(open).toHaveAttribute("href", "/renders?join=3");
  });

  it("does not join when fewer than two clip ids are given", async () => {
    renderRenders();
    await screen.findByText("Ridge");
    fireEvent.change(screen.getByPlaceholderText(/id клипов/i), { target: { value: "12" } });
    fireEvent.click(screen.getByRole("button", { name: /склеить/i }));
    expect(await screen.findByText(/минимум два id клипов/i)).toBeInTheDocument();
    expect(apiMock.factory.createComposition).not.toHaveBeenCalled();
  });

  it("cancels a queued generation", async () => {
    renderRenders();
    const row = (await screen.findByText("Ridge")).closest("tr") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: /отменить/i }));
    await waitFor(() => expect(apiMock.factory.cancelGeneration).toHaveBeenCalledWith(9));
  });

  it("retries a failed generation", async () => {
    apiMock.factory.generations.mockResolvedValue([failedGen]);
    renderRenders();
    const row = (await screen.findByText("Storm")).closest("tr") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: /повторить/i }));
    await waitFor(() => expect(apiMock.factory.retryGeneration).toHaveBeenCalledWith(11));
  });

  it("cancels a failed generation so it can be dismissed", async () => {
    apiMock.factory.generations.mockResolvedValue([failedGen]);
    renderRenders();
    const row = (await screen.findByText("Storm")).closest("tr") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: /отменить/i }));
    await waitFor(() => expect(apiMock.factory.cancelGeneration).toHaveBeenCalledWith(11));
  });

  it("does not open local switch modal without offer_local_switch", async () => {
    apiMock.factory.generations.mockResolvedValue([failedGen]);
    renderRenders();
    await screen.findByText("Storm");
    expect(screen.queryByRole("heading", { name: /переключить на локальный wan/i })).toBeNull();
  });

  it("opens local switch modal when offer_local_switch is set", async () => {
    apiMock.factory.generations.mockResolvedValue([
      {
        ...failedGen,
        last_error: "LOCAL_SWITCH_OFFER: fal: down",
        offer_local_switch: true,
      },
    ]);
    renderRenders();
    expect(
      await screen.findByRole("heading", { name: /переключить на локальный wan/i })
    ).toBeInTheDocument();
  });

  it("shows last_error for a failed generation", async () => {
    apiMock.factory.generations.mockResolvedValue([failedGen]);
    renderRenders();
    expect(await screen.findByText(/pollinations rejected/i)).toBeInTheDocument();
    expect(screen.getByText(/Локальный рендер/i)).toBeInTheDocument();
  });

  it("shows an error toast when cancel fails", async () => {
    apiMock.factory.cancelGeneration.mockRejectedValue(new Error("already running"));
    renderRenders();
    const row = (await screen.findByText("Ridge")).closest("tr") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: /отменить/i }));
    expect(await screen.findByText(/already running/i)).toBeInTheDocument();
  });
});
