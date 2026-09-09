import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useHotkeys } from "../useHotkeys";

describe("useHotkeys", () => {
  it("fires a single-letter shortcut", () => {
    const j = vi.fn();
    renderHook(() => useHotkeys({ j }));
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "j" }));
    expect(j).toHaveBeenCalledOnce();
  });

  it("does not steal a letter typed into an input", () => {
    const j = vi.fn();
    renderHook(() => useHotkeys({ j }));
    const input = document.createElement("input");
    document.body.appendChild(input);
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "j", bubbles: true }));
    expect(j).not.toHaveBeenCalled();
    input.remove();
  });

  it("fires mod+k even while typing", () => {
    const open = vi.fn((e: KeyboardEvent) => e.preventDefault());
    renderHook(() => useHotkeys({ "mod+k": open }));
    const input = document.createElement("input");
    document.body.appendChild(input);
    input.dispatchEvent(
      new KeyboardEvent("keydown", { key: "k", ctrlKey: true, bubbles: true })
    );
    expect(open).toHaveBeenCalledOnce();
    input.remove();
  });

  it("does not fire a letter shortcut when Ctrl is held", () => {
    const c = vi.fn();
    renderHook(() => useHotkeys({ c }));
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "c", ctrlKey: true }));
    expect(c).not.toHaveBeenCalled();
  });
});
