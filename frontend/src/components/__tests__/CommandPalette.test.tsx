import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../../api/client";
import { CommandPalette } from "../CommandPalette";

const useAuthMock = vi.hoisted(() => vi.fn());

vi.mock("../../api/client", () => ({
  api: {
    accounts: { list: vi.fn() },
    jobs: { list: vi.fn() },
    videos: { list: vi.fn() },
  },
}));

vi.mock("../../context/AuthContext", () => ({
  useAuth: useAuthMock,
}));

function authStub(role: "owner" | "operator" | null) {
  return {
    role,
    state: role ? { state: "authed" as const, token: "t" } : { state: "open" as const },
    login: vi.fn(),
    logout: vi.fn(),
    retryBootstrap: vi.fn(),
    authRequired: role != null,
  };
}

function renderPalette(onClose = vi.fn()) {
  return render(
    <MemoryRouter>
      <CommandPalette onClose={onClose} />
    </MemoryRouter>
  );
}

beforeEach(() => {
  useAuthMock.mockReturnValue(authStub("owner"));
  vi.mocked(api.accounts.list).mockResolvedValue([
    { id: 1, username: "quiet", platform: "instagram" } as never,
  ]);
  vi.mocked(api.jobs.list).mockResolvedValue([]);
  vi.mocked(api.videos.list).mockResolvedValue([]);
});

describe("CommandPalette", () => {
  it("lists pages to jump to", async () => {
    renderPalette();
    expect(await screen.findByRole("button", { name: /Календарь/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Администрирование/ })).toBeInTheDocument();
  });

  it("finds an account by part of its name", async () => {
    renderPalette();
    await userEvent.type(await screen.findByLabelText("Куда перейти"), "quie");
    expect(await screen.findByRole("button", { name: /@quiet/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Календарь/ })).not.toBeInTheDocument();
  });

  it("says so when nothing matches", async () => {
    renderPalette();
    await userEvent.type(await screen.findByLabelText("Куда перейти"), "zebra");
    expect(await screen.findByText("Ничего с таким названием.")).toBeInTheDocument();
  });

  it("still lists pages when accounts cannot be read", async () => {
    vi.mocked(api.accounts.list).mockRejectedValueOnce(new Error("no"));
    renderPalette();
    expect(await screen.findByRole("button", { name: /Библиотека/ })).toBeInTheDocument();
  });

  it("closes once something is chosen", async () => {
    const onClose = vi.fn();
    renderPalette(onClose);
    await userEvent.click(await screen.findByRole("button", { name: /Настройки/ }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("hides owner pages from an operator", async () => {
    useAuthMock.mockReturnValue(authStub("operator"));
    renderPalette();
    expect(await screen.findByRole("button", { name: /Календарь/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Настройки/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Доступы/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Администрирование/ })).not.toBeInTheDocument();
  });

  it("puts an icon on the Dashboard row", async () => {
    renderPalette();
    const row = await screen.findByRole("button", { name: /Панель/ });
    expect(row.querySelector("svg")).toBeTruthy();
  });
});
