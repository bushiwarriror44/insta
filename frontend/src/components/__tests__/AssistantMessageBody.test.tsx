import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AssistantMessageBody } from "../AssistantMessageBody";

vi.mock("../DiagnosticLogPanel", () => ({
  copyTextToClipboard: vi.fn(async () => true),
}));

describe("AssistantMessageBody", () => {
  it("renders links and code blocks", () => {
    render(
      <AssistantMessageBody
        content={'Смотри https://example.com/test\n\n```json\n{"ok":true}\n```\n\nкод `foo`'}
      />
    );
    const link = screen.getByRole("link", { name: /example\.com/ });
    expect(link).toHaveAttribute("href", "https://example.com/test");
    expect(screen.getByText('{"ok":true}')).toBeInTheDocument();
    expect(screen.getByText("foo")).toBeInTheDocument();
  });

  it("streaming mode linkifies URLs and hides copy", () => {
    render(
      <AssistantMessageBody content="Смотри https://example.com/live" streaming showCaret />
    );
    expect(screen.getByRole("link", { name: /example\.com/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /скопировать ответ/i })).not.toBeInTheDocument();
    expect(document.querySelector(".assistant-stream-caret")).toBeTruthy();
  });

  it("copies content when copy is clicked", async () => {
    const onCopyToast = vi.fn();
    const user = userEvent.setup();
    render(<AssistantMessageBody content="ответ агента" onCopyToast={onCopyToast} />);
    await user.click(screen.getByRole("button", { name: /скопировать ответ/i }));
    expect(onCopyToast).toHaveBeenCalledWith(true);
  });
});
