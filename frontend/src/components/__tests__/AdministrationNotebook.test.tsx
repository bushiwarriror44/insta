import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../../api/client";
import { AdministrationNotebook } from "../AdministrationNotebook";

vi.mock("../../api/client", () => ({
  api: {
    adminNotes: {
      get: vi.fn(),
      update: vi.fn(),
    },
  },
  formatApiError: (err: unknown) => String(err),
}));

const push = vi.fn();
vi.mock("../../context/ToastContext", () => ({
  useToast: () => ({ push }),
}));

beforeEach(() => {
  push.mockReset();
  vi.mocked(api.adminNotes.get).mockResolvedValue({ content: "", updated_at: null });
  vi.mocked(api.adminNotes.update).mockImplementation(async (content: string) => ({
    content,
    updated_at: "2026-09-21T00:00:00Z",
  }));
});

afterEach(() => {
  vi.useRealTimers();
});

describe("AdministrationNotebook", () => {
  it("loads empty notes and saves immediately from the button", async () => {
    const user = userEvent.setup();
    render(<AdministrationNotebook />);
    const field = await screen.findByLabelText(/текст блокнота/i);
    await user.type(field, "Salad org acme");
    await user.click(screen.getByRole("button", { name: /сохранить сейчас/i }));
    await waitFor(() =>
      expect(api.adminNotes.update).toHaveBeenCalledWith("Salad org acme")
    );
    expect(await screen.findByText(/сохранено/i)).toBeInTheDocument();
  });

  it("autosaves about two seconds after the last keystroke", async () => {
    render(<AdministrationNotebook />);
    const field = await screen.findByLabelText(/текст блокнота/i);
    vi.useFakeTimers();
    fireEvent.change(field, { target: { value: "host" } });
    expect(api.adminNotes.update).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1999);
    });
    expect(api.adminNotes.update).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(api.adminNotes.update).toHaveBeenCalledWith("host");
  });
});
