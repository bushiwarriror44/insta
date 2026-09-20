import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Administration } from "../Administration";

const swaggerMock = vi.hoisted(() => vi.fn(() => ({ destroy: vi.fn() })));
const useAuthMock = vi.hoisted(() => vi.fn());

vi.mock("swagger-ui-dist/swagger-ui-bundle.js", () => ({
  default: swaggerMock,
}));

vi.mock("../../context/AuthContext", () => ({
  useAuth: useAuthMock,
}));

vi.mock("../../context/ToastContext", () => ({
  useToast: () => ({ push: vi.fn() }),
}));

vi.mock("../../api/client", () => ({
  api: {
    gpu: {
      status: vi.fn().mockResolvedValue({
        configured: false,
        status: null,
        billing: false,
        allocating_count: 0,
        creating_count: 0,
        running_count: 0,
        stopping_count: 0,
        chat_ok: false,
        detail: "Задайте SALAD_API_KEY и имена группы в .env",
      }),
      start: vi.fn(),
      stop: vi.fn(),
    },
    adminNotes: {
      get: vi.fn().mockResolvedValue({ content: "", updated_at: null }),
      update: vi.fn(),
    },
  },
  formatApiError: (err: unknown) => String(err),
}));

function HashProbe() {
  const location = useLocation();
  return <span data-testid="admin-hash">{location.hash}</span>;
}

function renderPage(path = "/administration") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/" element={<div>HOME</div>} />
        <Route
          path="/administration"
          element={
            <>
              <HashProbe />
              <Administration />
            </>
          }
        />
      </Routes>
    </MemoryRouter>
  );
}

beforeEach(() => {
  swaggerMock.mockClear();
  useAuthMock.mockReset();
  window.location.hash = "";
});

describe("Administration page", () => {
  it("redirects operators", async () => {
    useAuthMock.mockReturnValue({
      role: "operator",
      state: { state: "authed", token: "op" },
      authRequired: true,
    });
    renderPage();
    expect(await screen.findByText("HOME")).toBeInTheDocument();
    expect(swaggerMock).not.toHaveBeenCalled();
  });

  it("opens the overview tab without mounting swagger", async () => {
    useAuthMock.mockReturnValue({
      role: "owner",
      state: { state: "authed", token: "owner-tok" },
      authRequired: true,
    });
    renderPage();
    expect(await screen.findByRole("heading", { name: /администрирование/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /обзор/i })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("heading", { name: /gpu salad/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /реализация/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /^оплата$/i })).toBeInTheDocument();
    expect(screen.getByText(/create_app/)).toBeInTheDocument();
    expect(screen.getByText(/карточка gpu salad на этой странице/i)).toBeInTheDocument();
    expect(screen.getByText(/0\.05 usd за секунду/i)).toBeInTheDocument();
    expect(screen.queryByTestId("swagger-host")).not.toBeInTheDocument();
    expect(swaggerMock).not.toHaveBeenCalled();
  });

  it("switches to the notebook tab", async () => {
    useAuthMock.mockReturnValue({
      role: "owner",
      state: { state: "authed", token: "owner-tok" },
      authRequired: true,
    });
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole("tab", { name: /блокнот/i }));
    expect(await screen.findByRole("heading", { name: /^блокнот$/i })).toBeInTheDocument();
    expect(screen.getByTestId("admin-hash")).toHaveTextContent("#notes");
    expect(screen.getByLabelText(/текст блокнота/i)).toBeInTheDocument();
    expect(swaggerMock).not.toHaveBeenCalled();
  });

  it("opens the API tab from the #api hash", async () => {
    useAuthMock.mockReturnValue({
      role: "owner",
      state: { state: "authed", token: "owner-tok" },
      authRequired: true,
    });
    renderPage("/administration#api");
    expect(screen.getByRole("tab", { name: /^api$/i })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("swagger-host")).toBeInTheDocument();
    await waitFor(() => expect(swaggerMock).toHaveBeenCalled());
  });

  it("mounts swagger on the API tab and sends the session token", async () => {
    useAuthMock.mockReturnValue({
      role: "owner",
      state: { state: "authed", token: "owner-tok" },
      authRequired: true,
    });
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole("tab", { name: /^api$/i }));
    expect(screen.getByTestId("swagger-host")).toBeInTheDocument();
    await waitFor(() => expect(swaggerMock).toHaveBeenCalled());
    const opts = swaggerMock.mock.calls[0][0] as {
      url: string;
      requestInterceptor: (req: { headers?: Record<string, string> }) => {
        headers?: Record<string, string>;
      };
    };
    expect(opts.url).toBe("/api/openapi.json");
    const intercepted = opts.requestInterceptor({ headers: {} });
    expect(intercepted.headers?.Authorization).toBe("Bearer owner-tok");
  });

  it("mounts swagger in open mode without a bearer", async () => {
    useAuthMock.mockReturnValue({
      role: null,
      state: { state: "open" },
      authRequired: false,
    });
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole("tab", { name: /^api$/i }));
    await waitFor(() => expect(swaggerMock).toHaveBeenCalled());
    const opts = swaggerMock.mock.calls[0][0] as {
      requestInterceptor: (req: { headers?: Record<string, string> }) => {
        headers?: Record<string, string>;
      };
    };
    const intercepted = opts.requestInterceptor({ headers: {} });
    expect(intercepted.headers?.Authorization).toBeUndefined();
  });
});
