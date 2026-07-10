import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Modal } from "../Modal";

describe("Modal", () => {
  it("does not render when open is false", () => {
    render(
      <Modal open={false} onClose={() => {}} title="Hidden">
        <span>body</span>
      </Modal>
    );
    expect(screen.queryByText("Hidden")).not.toBeInTheDocument();
    expect(screen.queryByText("body")).not.toBeInTheDocument();
  });

  it("renders title, body and footer when open", () => {
    render(
      <Modal
        open
        onClose={() => {}}
        title="My modal"
        footer={<button>OK</button>}
      >
        <span>body content</span>
      </Modal>
    );
    expect(screen.getByText("My modal")).toBeInTheDocument();
    expect(screen.getByText("body content")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "OK" })).toBeInTheDocument();
  });

  it("calls onClose on Escape", () => {
    const onClose = vi.fn();
    render(
      <Modal open onClose={onClose} title="t">
        body
      </Modal>
    );
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does not call onClose on other keys", () => {
    const onClose = vi.fn();
    render(
      <Modal open onClose={onClose} title="t">
        body
      </Modal>
    );
    fireEvent.keyDown(window, { key: "a" });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("calls onClose when clicking the backdrop", () => {
    const onClose = vi.fn();
    const { container } = render(
      <Modal open onClose={onClose} title="t">
        body
      </Modal>
    );
    const backdrop = container.querySelector(".fixed.inset-0") as HTMLElement;
    expect(backdrop).not.toBeNull();
    fireEvent.mouseDown(backdrop);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does NOT call onClose when clicking inside the dialog", () => {
    const onClose = vi.fn();
    render(
      <Modal open onClose={onClose} title="t">
        <span>body</span>
      </Modal>
    );
    fireEvent.mouseDown(screen.getByText("body"));
    expect(onClose).not.toHaveBeenCalled();
  });

  it("calls onClose via the X header button", () => {
    const onClose = vi.fn();
    render(
      <Modal open onClose={onClose} title="t">
        body
      </Modal>
    );
    const xBtn = screen.getByRole("button", { name: /закрыть/i });
    fireEvent.click(xBtn);
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
