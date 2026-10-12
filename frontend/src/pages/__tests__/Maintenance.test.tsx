import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../../context/ToastContext";
import type { RuntimeOut } from "../../api/types";
import { Maintenance } from "../Maintenance";

const useAuthMock = vi.hoisted(() => vi.fn());

const apiMock = vi.hoisted(() => ({
  maintenance: {
    runtime: vi.fn(),
    backups: vi.fn(),
    setContext: vi.fn(),
    takeBackup: vi.fn(),
    restoreBackup: vi.fn(),
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

vi.mock("../../context/AuthContext", () => ({
  useAuth: useAuthMock,
}));

const offline: RuntimeOut = {
  reachable: false,
  base_url: "http://localhost:11434",
  models: [],
  model: "qwen3:8b",
  loaded: [],
  context: 8192,
  detail: "offline",
};

const online: RuntimeOut = {
  ...offline,
  reachable: true,
  detail: null,
  loaded: [{ name: "qwen3:8b", context: 8192, size_bytes: 1 }],
};

const copy = {
  name: "app-20260908-210000.db",
  bytes: 2048,
  taken_at: "2026-09-08T21:00:00+00:00",
};

beforeEach(() => {
  apiMock.maintenance.runtime.mockReset();
  apiMock.maintenance.backups.mockReset();
  apiMock.maintenance.setContext.mockReset();
  apiMock.maintenance.takeBackup.mockReset();
  apiMock.maintenance.restoreBackup.mockReset();
  apiMock.maintenance.runtime.mockResolvedValue(offline);
  apiMock.maintenance.backups.mockResolvedValue([]);
  apiMock.maintenance.setContext.mockResolvedValue(online);
  apiMock.maintenance.takeBackup.mockResolvedValue(copy);
  apiMock.maintenance.restoreBackup.mockResolvedValue({ restored: "/data/app.db" });
  useAuthMock.mockReset();
  useAuthMock.mockReturnValue({ role: "owner" });
});

function renderMaintenance() {
  return render(
    <MemoryRouter>
      <ToastProvider>
        <Maintenance />
      </ToastProvider>
    </MemoryRouter>
  );
}

describe("Maintenance page", () => {
  it("shows ollama offline and keeps Apply disabled", async () => {
    renderMaintenance();
    expect(await screen.findByRole("heading", { name: /обслуживание/i })).toBeInTheDocument();
    expect(screen.getByText(/ollama/i)).toBeInTheDocument();
    expect(screen.getByText(/offline/i)).toBeInTheDocument();
    expect(screen.getByText(/модель: qwen3:8b/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /применить/i })).toBeDisabled();
  });

  it("hides restore for operators", async () => {
    useAuthMock.mockReturnValue({ role: "operator" });
    apiMock.maintenance.backups.mockResolvedValue([copy]);
    renderMaintenance();
    expect(await screen.findByText(/app-20260908-210000\.db/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /восстановить/i })).not.toBeInTheDocument();
  });

  it("applies context when ollama is reachable", async () => {
    apiMock.maintenance.runtime.mockResolvedValue(online);
    renderMaintenance();
    expect(await screen.findByText(/доступна/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /применить/i }));
    await waitFor(() => expect(apiMock.maintenance.setContext).toHaveBeenCalledWith(8192));
  });

  it("adds a backup row without noop Open link", async () => {
    renderMaintenance();
    await screen.findByText(/модель: qwen3:8b/i);
    apiMock.maintenance.takeBackup.mockImplementation(async () => {
      apiMock.maintenance.backups.mockResolvedValue([copy]);
      return copy;
    });
    fireEvent.click(screen.getByRole("button", { name: /снять копию/i }));
    expect(await screen.findByText(/app-20260908-210000\.db/i)).toBeInTheDocument();
    expect(await screen.findByText(/копия снята/i)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /открыть/i })).not.toBeInTheDocument();
  });

  it("restores a backup after confirm", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    apiMock.maintenance.backups.mockResolvedValue([copy]);
    renderMaintenance();
    expect(await screen.findByText(/app-20260908-210000\.db/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /восстановить app-20260908-210000\.db/i }));
    await waitFor(() =>
      expect(apiMock.maintenance.restoreBackup).toHaveBeenCalledWith("app-20260908-210000.db")
    );
    expect(await screen.findByText(/база восстановлена/i)).toBeInTheDocument();
  });
});
