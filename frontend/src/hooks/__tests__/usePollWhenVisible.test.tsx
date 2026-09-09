import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { usePollWhenVisible } from "../usePollWhenVisible";

describe("usePollWhenVisible", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    Object.defineProperty(document, "hidden", { configurable: true, value: false });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("ticks immediately and again on the interval", () => {
    const tick = vi.fn();
    renderHook(() => usePollWhenVisible(tick, 1000));
    expect(tick).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(1000);
    expect(tick).toHaveBeenCalledTimes(2);
  });

  it("pauses while the tab is hidden", () => {
    const tick = vi.fn();
    renderHook(() => usePollWhenVisible(tick, 1000));
    Object.defineProperty(document, "hidden", { configurable: true, value: true });
    document.dispatchEvent(new Event("visibilitychange"));
    vi.advanceTimersByTime(5000);
    expect(tick).toHaveBeenCalledTimes(1);
  });

  it("does not re-tick just because the callback identity changed", () => {
    const first = vi.fn();
    const { rerender } = renderHook(
      ({ tick }) => usePollWhenVisible(tick, 1000),
      { initialProps: { tick: first } }
    );
    expect(first).toHaveBeenCalledTimes(1);
    const second = vi.fn();
    rerender({ tick: second });
    expect(first).toHaveBeenCalledTimes(1);
    expect(second).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1000);
    expect(second).toHaveBeenCalledTimes(1);
  });

  it("restarts immediately when restartKey changes", () => {
    const tick = vi.fn();
    const { rerender } = renderHook(
      ({ key }) => usePollWhenVisible(tick, 1000, true, key),
      { initialProps: { key: "a" } }
    );
    expect(tick).toHaveBeenCalledTimes(1);
    rerender({ key: "b" });
    expect(tick).toHaveBeenCalledTimes(2);
  });

  it("does not tick while the tab is already hidden on mount", () => {
    Object.defineProperty(document, "hidden", { configurable: true, value: true });
    const tick = vi.fn();
    renderHook(() => usePollWhenVisible(tick, 1000));
    expect(tick).not.toHaveBeenCalled();
    vi.advanceTimersByTime(5000);
    expect(tick).not.toHaveBeenCalled();
    Object.defineProperty(document, "hidden", { configurable: true, value: false });
    document.dispatchEvent(new Event("visibilitychange"));
    expect(tick).toHaveBeenCalledTimes(1);
  });
});
