import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import { QubaxPanel } from "../QubaxPanel";

const pushMock = vi.hoisted(() => vi.fn());
const confirmMock = vi.hoisted(() => vi.fn(async () => true));

const apiMock = vi.hoisted(() => ({
  qubax: {
    status: vi.fn(),
    setApiKey: vi.fn(),
    saveForm: vi.fn(),
    models: vi.fn(),
    marketPrices: vi.fn(),
    estimate: vi.fn(),
    modelDetail: vi.fn(),
    listJobs: vi.fn(),
    createBatch: vi.fn(),
    createJob: vi.fn(),
    getJob: vi.fn(),
    importJob: vi.fn(),
  },
  videos: { list: vi.fn() },
}));

vi.mock("../../api/client", () => ({
  api: apiMock,
  formatApiError: (e: unknown) => String(e),
}));

vi.mock("../../context/ToastContext", () => ({
  useToast: () => ({ push: pushMock }),
}));

vi.mock("../../context/ConfirmContext", () => ({
  useConfirm: () => confirmMock,
}));

vi.mock("../../hooks/usePollWhenVisible", () => ({
  usePollWhenVisible: () => {},
}));

describe("QubaxPanel", () => {
  beforeEach(() => {
    vi.useRealTimers();
    pushMock.mockReset();
    apiMock.qubax.status.mockReset();
    apiMock.qubax.setApiKey.mockReset();
    apiMock.qubax.models.mockReset();
    apiMock.qubax.listJobs.mockReset();
    apiMock.qubax.createBatch.mockReset();
    apiMock.videos.list.mockReset();
    apiMock.qubax.status.mockResolvedValue({
      configured: false,
      key_from_env: false,
    });
    apiMock.videos.list.mockResolvedValue([]);
    apiMock.qubax.listJobs.mockResolvedValue({ items: [], total: 0 });
    apiMock.qubax.saveForm.mockResolvedValue({ configured: true, key_from_env: false });
    apiMock.qubax.modelDetail.mockResolvedValue({});
    apiMock.qubax.marketPrices.mockResolvedValue({ prices: {} });
    apiMock.qubax.estimate.mockResolvedValue({
      items: [],
      jobs_count: 0,
      total_usd: null,
    });
  });

  it("shows api key field when not configured", async () => {
    render(
      <MemoryRouter>
        <QubaxPanel />
      </MemoryRouter>
    );
    expect(await screen.findByTestId("qubax-api-key")).toBeInTheDocument();
  });

  it("calls setApiKey on save", async () => {
    apiMock.qubax.setApiKey.mockResolvedValue({
      configured: true,
      key_from_env: false,
      balance: 1,
    });
    apiMock.qubax.models.mockResolvedValue({ presets: [], models: [] });
    render(
      <MemoryRouter>
        <QubaxPanel />
      </MemoryRouter>
    );
    const input = await screen.findByTestId("qubax-api-key");
    fireEvent.change(input, { target: { value: "qbx_live_test" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() =>
      expect(apiMock.qubax.setApiKey).toHaveBeenCalledWith("qbx_live_test")
    );
  });

  it("debounces saveForm when prompt changes", async () => {
    apiMock.qubax.status.mockResolvedValue({
      configured: true,
      key_from_env: false,
      balance: 5,
      settings: {
        api_public_base_url: "",
        api_public_source: "none",
        api_public_configured: false,
        default_model: "video-gen",
        default_model_i2v: "uncensored-i2v-pro",
      },
    });
    apiMock.qubax.models.mockResolvedValue({ presets: [], models: [] });
    apiMock.qubax.marketPrices.mockResolvedValue({ prices: {} });
    render(
      <MemoryRouter>
        <QubaxPanel />
      </MemoryRouter>
    );
    await screen.findByTestId("qubax-prompt");
    await new Promise((r) => setTimeout(r, 120));
    fireEvent.change(screen.getByTestId("qubax-prompt"), { target: { value: "autosave me" } });
    await waitFor(() => expect(apiMock.qubax.saveForm).toHaveBeenCalled(), { timeout: 3000 });
  });

  it("batch button triggers createBatch when configured", async () => {
    apiMock.qubax.status.mockResolvedValue({
      configured: true,
      key_from_env: false,
      balance: 5,
    });
    apiMock.qubax.models.mockResolvedValue({
      presets: [{ id: "video-gen", label: "Video Gen" }],
      models: [],
    });
    apiMock.qubax.createBatch.mockResolvedValue({
      items: [{ id: 1, external_id: "x", model: "video-gen", prompt: "p", status: "pending" }],
      total: 1,
    });
    render(
      <MemoryRouter>
        <QubaxPanel />
      </MemoryRouter>
    );
    await waitFor(() => expect(screen.getByTestId("qubax-prompt")).toBeInTheDocument());
    fireEvent.change(screen.getByTestId("qubax-prompt"), { target: { value: "test prompt" } });
    fireEvent.click(screen.getByRole("button", { name: /Добавить вариант/i }));
    fireEvent.click(screen.getByTestId("qubax-batch"));
    await waitFor(() => expect(apiMock.qubax.createBatch).toHaveBeenCalled());
  });

  it("apply suggested public url fills input", async () => {
    apiMock.qubax.status.mockResolvedValue({
      configured: true,
      key_from_env: false,
      balance: 5,
      settings: {
        api_public_base_url: "",
        api_public_source: "none",
        api_public_configured: false,
        suggested_api_public_base_url: "https://panel.example.com",
        default_model: "video-gen",
        default_model_i2v: "uncensored-i2v-pro",
      },
    });
    apiMock.qubax.models.mockResolvedValue({ presets: [], models: [] });
    apiMock.qubax.marketPrices.mockResolvedValue({ prices: {} });
    render(
      <MemoryRouter>
        <QubaxPanel />
      </MemoryRouter>
    );
    await waitFor(() => expect(screen.getByTestId("qubax-apply-public-url")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("qubax-apply-public-url"));
    expect((screen.getByTestId("qubax-public-url") as HTMLInputElement).value).toBe(
      "https://panel.example.com"
    );
  });
});
