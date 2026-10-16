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
  videos: { list: vi.fn(), upload: vi.fn() },
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
        width: 720,
        height: 1280,
        duration_s: 5,
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

  it("sends the chosen frame size and duration", async () => {
    renderRenders();
    await screen.findByText("Ridge");
    fireEvent.change(screen.getByRole("combobox", { name: "Размер кадра" }), {
      target: { value: "16:9" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: "Длительность" }), {
      target: { value: "10" },
    });
    fireEvent.change(screen.getByPlaceholderText("Промпт"), { target: { value: "wide ridge" } });
    fireEvent.click(screen.getByRole("button", { name: /поставить рендер/i }));
    await waitFor(() =>
      expect(apiMock.factory.createGeneration).toHaveBeenCalledWith({
        prompt: "wide ridge",
        backend: "auto",
        account_id: undefined,
        width: 1280,
        height: 720,
        duration_s: 10,
      })
    );
  });

  it("keeps local Wan on 5 or 10 seconds", async () => {
    apiMock.factory.backends.mockResolvedValue([
      { name: "local", healthy: true, licence: "Apache-2.0", experimental: false, detail: "" },
    ]);
    renderRenders();
    await screen.findByText("Ridge");
    fireEvent.click(screen.getByRole("button", { name: /^local/i }));
    const duration = screen.getByRole("combobox", { name: "Длительность" });
    expect(within(duration).queryByRole("option", { name: "15 с" })).toBeNull();
    expect(within(duration).getByRole("option", { name: "10 с" })).toBeInTheDocument();
    expect(screen.getByText(/длиннее 10 с не снимет/i)).toBeInTheDocument();
  });

  it("sends 30 seconds for fal and notes the snap", async () => {
    renderRenders();
    await screen.findByText("Ridge");
    fireEvent.click(screen.getByRole("button", { name: /^fal/i }));
    fireEvent.change(screen.getByRole("combobox", { name: "Длительность" }), {
      target: { value: "30" },
    });
    fireEvent.change(screen.getByPlaceholderText("Промпт"), { target: { value: "long fal" } });
    fireEvent.click(screen.getByRole("button", { name: /поставить рендер/i }));
    expect(screen.getByText(/fal снимет 5 или 10/i)).toBeInTheDocument();
    await waitFor(() =>
      expect(apiMock.factory.createGeneration).toHaveBeenCalledWith({
        prompt: "long fal",
        backend: "fal",
        account_id: undefined,
        width: 720,
        height: 1280,
        duration_s: 30,
      })
    );
  });

  it("applies a Reels preset and optional seed", async () => {
    renderRenders();
    await screen.findByText("Ridge");
    fireEvent.change(screen.getByRole("combobox", { name: "Платформа" }), {
      target: { value: "reels" },
    });
    fireEvent.change(screen.getByLabelText("Негативный промпт"), {
      target: { value: "текст, логотип" },
    });
    fireEvent.change(screen.getByLabelText("Seed"), { target: { value: "42" } });
    fireEvent.change(screen.getByPlaceholderText("Промпт"), { target: { value: "reels apple" } });
    fireEvent.click(screen.getByRole("button", { name: /поставить рендер/i }));
    expect(screen.getByText(/файл остаётся mp4/i)).toBeInTheDocument();
    await waitFor(() =>
      expect(apiMock.factory.createGeneration).toHaveBeenCalledWith({
        prompt: "reels apple",
        backend: "auto",
        account_id: undefined,
        width: 1080,
        height: 1920,
        duration_s: 15,
        negative_prompt: "текст, логотип",
        seed: 42,
      })
    );
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
        width: 720,
        height: 1280,
        duration_s: 5,
      })
    );
  });

  it("does not render a duplicate backend select", async () => {
    renderRenders();
    await screen.findByText("Ridge");
    expect(screen.queryByRole("combobox", { name: /^бэкенд$/i })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /^fal/i }));
    fireEvent.change(screen.getByPlaceholderText("Промпт"), { target: { value: "only fal" } });
    fireEvent.click(screen.getByRole("button", { name: /поставить рендер/i }));
    await waitFor(() =>
      expect(apiMock.factory.createGeneration).toHaveBeenCalledWith({
        prompt: "only fal",
        backend: "fal",
        account_id: undefined,
        width: 720,
        height: 1280,
        duration_s: 5,
      })
    );
  });

  it("queues a render with a library image reference", async () => {
    apiMock.videos.list.mockResolvedValue([
      { filename: "still.jpg", media_type: "image", size_bytes: 12, modified_at: "" },
    ]);
    renderRenders();
    await screen.findByText("Ridge");
    fireEvent.change(screen.getByRole("combobox", { name: /или из библиотеки/i }), {
      target: { value: "still.jpg" },
    });
    fireEvent.change(screen.getByPlaceholderText("Промпт"), { target: { value: "like this still" } });
    fireEvent.click(screen.getByRole("button", { name: /поставить рендер/i }));
    await waitFor(() =>
      expect(apiMock.factory.createGeneration).toHaveBeenCalledWith({
        prompt: "like this still",
        backend: "auto",
        account_id: undefined,
        width: 720,
        height: 1280,
        duration_s: 5,
        input_mode: "image_to_video",
        reference_filename: "still.jpg",
        reference_role: "start_image",
      })
    );
  });

  it("uploads a dropped image and sends it as the reference", async () => {
    apiMock.videos.upload.mockResolvedValue({
      filename: "paste.png",
      media_type: "image",
      size_bytes: 8,
    });
    renderRenders();
    await screen.findByText("Ridge");
    const file = new File([new Uint8Array([1, 2, 3])], "paste.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText(/выбрать файл референса/i), {
      target: { files: [file] },
    });
    expect(await screen.findByText("paste.png")).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("Промпт"), { target: { value: "match the frame" } });
    fireEvent.click(screen.getByRole("button", { name: /поставить рендер/i }));
    await waitFor(() =>
      expect(apiMock.factory.createGeneration).toHaveBeenCalledWith({
        prompt: "match the frame",
        backend: "auto",
        account_id: undefined,
        width: 720,
        height: 1280,
        duration_s: 5,
        input_mode: "image_to_video",
        reference_filename: "paste.png",
        reference_role: "start_image",
      })
    );
  });

  it("refuses Ken Burns when the reference is a video", async () => {
    apiMock.videos.list.mockResolvedValue([
      { filename: "motion.mp4", media_type: "video", size_bytes: 20, modified_at: "" },
    ]);
    renderRenders();
    await screen.findByText("Ridge");
    fireEvent.change(screen.getByRole("combobox", { name: /или из библиотеки/i }), {
      target: { value: "motion.mp4" },
    });
    fireEvent.click(screen.getByRole("button", { name: /ken burns/i }));
    fireEvent.change(screen.getByPlaceholderText("Промпт"), { target: { value: "pan" } });
    fireEvent.click(screen.getByRole("button", { name: /поставить рендер/i }));
    expect(await screen.findByText(/ken burns работает только с фото/i)).toBeInTheDocument();
    expect(apiMock.factory.createGeneration).not.toHaveBeenCalled();
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
        width: 720,
        height: 1280,
        duration_s: 5,
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

  it("hides a stale error while a generation is running", async () => {
    apiMock.factory.generations.mockResolvedValue([
      {
        ...queuedGen,
        id: 8,
        status: "running",
        stage: "рендер",
        last_error: "local: wan timed out — проверьте WAN_BASE_URL",
      },
    ]);
    renderRenders();
    expect(await screen.findByText("В работе")).toBeInTheDocument();
    expect(screen.queryByText(/wan timed out/i)).not.toBeInTheDocument();
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
