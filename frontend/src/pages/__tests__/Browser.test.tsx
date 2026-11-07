import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Browser } from "../Browser";

const apiMock = vi.hoisted(() => ({
  accounts: { list: vi.fn() },
  proxies: { list: vi.fn() },
}));

vi.mock("../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../api/client")>("../../api/client");
  return {
    ...actual,
    api: { ...actual.api, accounts: apiMock.accounts, proxies: apiMock.proxies },
  };
});

vi.mock("../../context/AuthContext", () => ({
  useAuth: () => ({ state: { state: "authed", token: "tok" } }),
}));

vi.mock("../../context/ToastContext", () => ({
  useToast: () => ({ push: vi.fn() }),
}));

vi.mock("../../components/LazyInstagramBrowserPanel", () => ({
  LazyInstagramBrowserPanel: ({ username }: { username: string }) => (
    <div data-testid="browser-panel">panel:{username}</div>
  ),
}));

vi.mock("../../components/FreeBrowserPanel", () => ({
  FreeBrowserPanel: () => <div data-testid="free-browser-panel" />,
}));

function renderBrowser(path = "/browser") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/browser" element={<Browser />} />
      </Routes>
    </MemoryRouter>
  );
}

beforeEach(() => {
  apiMock.accounts.list.mockReset();
  apiMock.proxies.list.mockReset();
  apiMock.proxies.list.mockResolvedValue([]);
  localStorage.clear();
});

describe("Browser page", () => {
  it("shows title and account list", async () => {
    apiMock.accounts.list.mockResolvedValue([
      {
        id: 1,
        username: "ytuser",
        platform: "youtube",
        proxy_label: "p1",
        status: "active",
      },
      {
        id: 2,
        username: "noproxy",
        platform: "youtube",
        proxy_label: null,
        status: "active",
      },
    ]);

    renderBrowser();

    expect(await screen.findByRole("heading", { name: "Браузер" })).toBeInTheDocument();
    expect(await screen.findByText("@ytuser")).toBeInTheDocument();
    expect(screen.getByText("нет прокси")).toBeInTheDocument();
  });

  it("loads panel for account with proxy from url", async () => {
    apiMock.accounts.list.mockResolvedValue([
      {
        id: 1,
        username: "ytuser",
        platform: "youtube",
        proxy_label: "p1",
        status: "active",
      },
    ]);

    renderBrowser("/browser?username=ytuser");

    expect(await screen.findByTestId("browser-panel")).toHaveTextContent("panel:ytuser");
  });

  it("shows empty proxy message when selected account has no proxy", async () => {
    apiMock.accounts.list.mockResolvedValue([
      {
        id: 2,
        username: "noproxy",
        platform: "youtube",
        proxy_label: null,
        status: "active",
      },
    ]);

    renderBrowser("/browser?username=noproxy");

    expect(await screen.findByText("Нужен прокси")).toBeInTheDocument();
  });

  it("shows free browser mode", async () => {
    apiMock.accounts.list.mockResolvedValue([]);
    renderBrowser("/browser?mode=free");
    expect(await screen.findByTestId("free-browser-panel")).toBeInTheDocument();
  });

  it("switches account on click", async () => {
    const user = userEvent.setup();
    apiMock.accounts.list.mockResolvedValue([
      {
        id: 1,
        username: "alice",
        platform: "instagram",
        proxy_label: "p1",
        status: "active",
      },
      {
        id: 2,
        username: "bob",
        platform: "instagram",
        proxy_label: "p2",
        status: "active",
      },
    ]);

    renderBrowser("/browser?username=alice");

    await waitFor(() => expect(screen.getByTestId("browser-panel")).toHaveTextContent("alice"));
    await user.click(screen.getByText("@bob"));
    await waitFor(() => expect(screen.getByTestId("browser-panel")).toHaveTextContent("bob"));
  });
});
