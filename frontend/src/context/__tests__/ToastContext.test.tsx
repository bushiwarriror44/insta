import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider, useToast } from "../ToastContext";

function wrapper({ children }: { children: React.ReactNode }) {
  return <ToastProvider>{children}</ToastProvider>;
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
