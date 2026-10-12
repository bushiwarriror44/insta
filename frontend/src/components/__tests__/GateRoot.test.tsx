import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GateRoot } from "../GateRoot";

const gateMock = vi.hoisted(() => vi.fn());

vi.mock("../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../api/client")>(
    "../../api/client"
  );
  return {
    ...actual,
    api: {
      ...actual.api,
      panel: { gate: gateMock },
      health: vi.fn().mockResolvedValue({ ok: true, version: "x", auth_required: false }),
      dashboard: vi.fn().mockResolvedValue({}),
      auth: { me: vi.fn().mockResolvedValue({ role: null, label: null }) },
    },
    configureAuth: vi.fn(),
  };
});

describe("GateRoot", () => {
  beforeEach(() => {
    gateMock.mockReset();
    document.title = "Админ-панель Reels";
  });

  it("shows fake 500 and sets title when gate denies the path", async () => {
    gateMock.mockResolvedValue({ allowed: false, entry_path: null });
    render(<GateRoot />);
    expect(await screen.findByTestId("fake-500")).toBeInTheDocument();
    expect(screen.getByText(/500 Internal Server Error/i)).toBeInTheDocument();
    await waitFor(() => {
      expect(document.title).toBe("500 Internal Server Error");
    });
  });

  it("shows retry UI on network error, not fake 500", async () => {
    gateMock.mockRejectedValue(new Error("Failed to fetch"));
    render(<GateRoot />);
    expect(await screen.findByTestId("gate-error")).toBeInTheDocument();
    expect(screen.queryByTestId("fake-500")).not.toBeInTheDocument();
    expect(screen.getByTestId("gate-retry")).toBeInTheDocument();
    expect(screen.getByText(/Сеть оборвала загрузку/i)).toBeInTheDocument();
  });

  it("retries gate after network error", async () => {
    const user = userEvent.setup();
    gateMock
      .mockRejectedValueOnce(new Error("Failed to fetch"))
      .mockResolvedValueOnce({ allowed: true, entry_path: "/secret" });
    render(<GateRoot />);
    expect(await screen.findByTestId("gate-error")).toBeInTheDocument();
    await user.click(screen.getByTestId("gate-retry"));
    await waitFor(() => {
      expect(screen.queryByTestId("fake-500")).not.toBeInTheDocument();
      expect(screen.queryByTestId("gate-error")).not.toBeInTheDocument();
    });
    expect(gateMock).toHaveBeenCalledTimes(2);
  });

  it("renders app shell when gate allows with entry_path", async () => {
    gateMock.mockResolvedValue({ allowed: true, entry_path: "/secret" });
    render(<GateRoot />);
    await waitFor(() => {
      expect(screen.queryByTestId("fake-500")).not.toBeInTheDocument();
      expect(screen.queryByTestId("gate-error")).not.toBeInTheDocument();
      expect(screen.queryByTestId("gate-loading")).not.toBeInTheDocument();
    });
  });

  it("renders app shell when gate allows without entry_path", async () => {
    gateMock.mockResolvedValue({ allowed: true, entry_path: null });
    render(<GateRoot />);
    await waitFor(() => {
      expect(screen.queryByTestId("fake-500")).not.toBeInTheDocument();
    });
  });
});
