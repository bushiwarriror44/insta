import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider, useToast } from "../ToastContext";

function wrapper({ children }: { children: React.ReactNode }) {
  return (
    <MemoryRouter>
      <ToastProvider>{children}</ToastProvider>
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.runOnlyPendingTimers();
  vi.useRealTimers();
});

describe("ToastContext", () => {
  it("renders pushed messages", () => {
    const { result } = renderHook(() => useToast(), { wrapper });
    act(() => {
      result.current.push("Hello world", "success");
    });
    expect(screen.getByText("Hello world")).toBeInTheDocument();
  });

  it("auto-dismisses after timeout", () => {
    const { result } = renderHook(() => useToast(), { wrapper });
    act(() => {
      result.current.push("bye in a bit", "info");
    });
    expect(screen.getByText("bye in a bit")).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(screen.queryByText("bye in a bit")).not.toBeInTheDocument();
  });

  it("supports manual close via the X button", () => {
    const { result } = renderHook(() => useToast(), { wrapper });
    act(() => {
      result.current.push("kill me", "error");
    });
    expect(screen.getByText("kill me")).toBeInTheDocument();
    const closeBtn = screen.getByRole("button", { name: /close/i });
    act(() => {
      fireEvent.click(closeBtn);
    });
    expect(screen.queryByText("kill me")).not.toBeInTheDocument();
  });

  it("renders multiple toasts at once", () => {
    const { result } = renderHook(() => useToast(), { wrapper });
    act(() => {
      result.current.push("first", "info");
      result.current.push("second", "error");
      result.current.push("third", "success");
    });
    expect(screen.getByText("first")).toBeInTheDocument();
    expect(screen.getByText("second")).toBeInTheDocument();
    expect(screen.getByText("third")).toBeInTheDocument();
  });

  it("renders an Open action that navigates", () => {
    const { result } = renderHook(() => useToast(), { wrapper });
    act(() => {
      result.current.push("Публикация в очереди", "success", {
        label: "Открыть",
        href: "/activity",
      });
    });
    expect(screen.getByRole("link", { name: "Открыть" })).toHaveAttribute("href", "/activity");
    act(() => {
      fireEvent.click(screen.getByRole("link", { name: "Открыть" }));
    });
    expect(screen.queryByText("Публикация в очереди")).not.toBeInTheDocument();
  });

  it("useToast throws when used outside provider", () => {
    function Probe() {
      useToast();
      return null;
    }
    const orig = console.error;
    console.error = () => {};
    try {
      expect(() => render(<Probe />)).toThrow(/useToast outside ToastProvider/);
    } finally {
      console.error = orig;
    }
  });
});
