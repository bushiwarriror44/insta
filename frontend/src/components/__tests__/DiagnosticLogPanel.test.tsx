import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  DiagnosticLogPanel,
  copyTextToClipboard,
  formatDiagnosticLogPlain,
} from "../DiagnosticLogPanel";

const sampleLines = [
  {
    ts: "2026-08-07T00:40:38Z",
    level: "info" as const,
    step: "session_probe",
    message: "Проверка сессии Instagram",
  },
  {
    ts: "2026-08-07T00:42:38Z",
    level: "error" as const,
    step: "session_probe",
    message: "session_id недействителен или истёк",
  },
];

describe("DiagnosticLogPanel", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("shows empty state", () => {
    render(<DiagnosticLogPanel lines={[]} emptyLabel="No logs" />);
    expect(screen.getByText("No logs")).toBeInTheDocument();
  });

  it("renders log lines with level badge", () => {
    render(
      <DiagnosticLogPanel
        lines={[
          {
            ts: "2026-07-03T12:00:00Z",
            level: "error",
            step: "proxy",
            message: "Connection refused",
          },
        ]}
      />
    );
    expect(screen.getByText("Прокси")).toBeInTheDocument();
    expect(screen.getByText("Connection refused")).toBeInTheDocument();
    expect(screen.getByText("error")).toBeInTheDocument();
  });

  it("copies plain-text log via Clipboard API", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });

    render(<DiagnosticLogPanel lines={sampleLines} />);
    fireEvent.click(screen.getByRole("button", { name: /копировать/i }));

    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    expect(writeText.mock.calls[0][0]).toBe(formatDiagnosticLogPlain(sampleLines));
    await screen.findByText(/скопировано/i);
  });

  it("falls back to execCommand when Clipboard API rejects", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("NotAllowedError"));
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    const execCommand = vi.fn().mockReturnValue(true);
    Object.defineProperty(document, "execCommand", {
      configurable: true,
      value: execCommand,
    });

    render(<DiagnosticLogPanel lines={sampleLines} />);
    fireEvent.click(screen.getByRole("button", { name: /копировать/i }));

    await waitFor(() => expect(execCommand).toHaveBeenCalledWith("copy"));
    await screen.findByText(/скопировано/i);
  });

  it("shows error when both clipboard paths fail", async () => {
    vi.stubGlobal("navigator", { clipboard: undefined });
    Object.defineProperty(document, "execCommand", {
      configurable: true,
      value: vi.fn().mockReturnValue(false),
    });

    render(<DiagnosticLogPanel lines={sampleLines} />);
    fireEvent.click(screen.getByRole("button", { name: /копировать/i }));

    await screen.findByText(/не удалось скопировать/i);
  });
});

describe("copyTextToClipboard", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("uses execCommand when clipboard is missing", async () => {
    vi.stubGlobal("navigator", {});
    const execCommand = vi.fn().mockReturnValue(true);
    Object.defineProperty(document, "execCommand", {
      configurable: true,
      value: execCommand,
    });
    await expect(copyTextToClipboard("hello")).resolves.toBe(true);
    expect(execCommand).toHaveBeenCalledWith("copy");
  });
});

describe("formatDiagnosticLogPlain", () => {
  it("formats ISO ts, UPPER level, raw step", () => {
    const text = formatDiagnosticLogPlain([
      {
        ts: "2026-08-07T00:40:38Z",
        level: "info",
        step: "session_probe",
        message: "hello",
      },
    ]);
    expect(text).toContain("[2026-08-07T00:40:38Z]");
    expect(text).toContain("INFO");
    expect(text).toContain("session_probe");
    expect(text).toContain("hello");
  });
});
