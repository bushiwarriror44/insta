import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DropZone } from "../DropZone";

function makeFile(name = "clip.mp4", type = "video/mp4") {
  return new File([new Uint8Array([1, 2, 3])], name, { type });
}

describe("DropZone", () => {
  it("renders default copy and accept hint", () => {
    render(<DropZone onFile={() => {}} />);
    expect(screen.getByText(/нажмите для выбора/i)).toBeInTheDocument();
    expect(screen.getByText(/\.mp4 \/ \.mov/)).toBeInTheDocument();
  });

  it("calls onFile after selecting a file via the hidden input", async () => {
    const onFile = vi.fn();
    const { container } = render(<DropZone onFile={onFile} />);
    const input = container.querySelector(
      'input[type="file"]'
    ) as HTMLInputElement;
    expect(input).not.toBeNull();
    const file = makeFile();
    await userEvent.upload(input, file);
    expect(onFile).toHaveBeenCalledTimes(1);
    expect(onFile).toHaveBeenCalledWith(file);
  });

  it("calls onFile after a drop event", () => {
    const onFile = vi.fn();
    const { container } = render(<DropZone onFile={onFile} />);
    const zone = container.firstChild as HTMLElement;
    const file = makeFile();

    fireEvent.dragOver(zone);
    fireEvent.drop(zone, { dataTransfer: { files: [file] } });
    expect(onFile).toHaveBeenCalledWith(file);
  });

  it("ignores drops with no files", () => {
    const onFile = vi.fn();
    const { container } = render(<DropZone onFile={onFile} />);
    const zone = container.firstChild as HTMLElement;
    fireEvent.drop(zone, { dataTransfer: { files: [] } });
    expect(onFile).not.toHaveBeenCalled();
  });

  it("does not invoke onFile when disabled", () => {
    const onFile = vi.fn();
    const { container } = render(<DropZone onFile={onFile} disabled />);
    const zone = container.firstChild as HTMLElement;
    fireEvent.drop(zone, { dataTransfer: { files: [makeFile()] } });
    expect(onFile).not.toHaveBeenCalled();
  });

  it("opens the file picker on click", () => {
    const onFile = vi.fn();
    const clickSpy = vi.spyOn(HTMLInputElement.prototype, "click");
    const { container } = render(<DropZone onFile={onFile} />);
    const zone = container.firstChild as HTMLElement;
    fireEvent.click(zone);
    expect(clickSpy).toHaveBeenCalled();
  });

  it("does not invoke onFile when staging until confirmed", async () => {
    const onFile = vi.fn();
    const { container } = render(<DropZone onFile={onFile} staging />);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const file = makeFile();
    await userEvent.upload(input, file);
    expect(onFile).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /^загрузить$/i }));
    expect(onFile).toHaveBeenCalledWith(file);
  });

  it("does not open picker on click when disabled", () => {
    const onFile = vi.fn();
    const clickSpy = vi.spyOn(HTMLInputElement.prototype, "click");
    const { container } = render(<DropZone onFile={onFile} disabled />);
    const zone = container.firstChild as HTMLElement;
    fireEvent.click(zone);
    expect(clickSpy).not.toHaveBeenCalled();
  });
});
