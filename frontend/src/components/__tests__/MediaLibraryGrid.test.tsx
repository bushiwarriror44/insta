import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { VideoOut } from "../../api/types";
import { MediaLibraryGrid } from "../MediaLibraryGrid";

vi.mock("../../api/media", () => ({
  fetchMediaObjectUrl: vi.fn(async () => "blob:mock"),
  revokeMediaObjectUrl: vi.fn(),
  formatBytes: () => "1 KB",
  formatDuration: () => "0:30",
}));

const items: VideoOut[] = [
  {
    filename: "reel.mp4",
    size_bytes: 1000,
    modified_at: new Date().toISOString(),
    media_type: "video",
    duration_sec: 30,
  },
  {
    filename: "pic.jpg",
    size_bytes: 500,
    modified_at: new Date().toISOString(),
    media_type: "image",
  },
];

const baseProps = {
  items,
  selectedFilename: "reel.mp4" as string | null,
  checkedFilenames: new Set<string>(),
  tab: "video" as const,
  search: "",
  onTabChange: () => {},
  onSearchChange: () => {},
  onSelect: () => {},
  onToggleChecked: () => {},
  onClearChecked: () => {},
  onDownloadArchive: () => {},
  onQuickPublish: () => {},
};

describe("MediaLibraryGrid", () => {
  it("renders video cards and calls onSelect", () => {
    const onSelect = vi.fn();
    render(<MediaLibraryGrid {...baseProps} onSelect={onSelect} />);
    expect(screen.getByText("reel.mp4")).toBeInTheDocument();
    fireEvent.click(screen.getByText("reel.mp4"));
    expect(onSelect).toHaveBeenCalledWith(items[0]);
  });

  it("calls onQuickPublish from card button", () => {
    const onQuickPublish = vi.fn();
    render(
      <MediaLibraryGrid
        {...baseProps}
        selectedFilename={null}
        onQuickPublish={onQuickPublish}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /быстрая публикация reel\.mp4/i }));
    expect(onQuickPublish).toHaveBeenCalledWith(items[0]);
  });

  it("toggles checkbox without selecting preview and downloads ZIP", () => {
    const onSelect = vi.fn();
    const onToggleChecked = vi.fn();
    const onDownloadArchive = vi.fn();
    render(
      <MediaLibraryGrid
        {...baseProps}
        checkedFilenames={new Set(["reel.mp4"])}
        onSelect={onSelect}
        onToggleChecked={onToggleChecked}
        onDownloadArchive={onDownloadArchive}
      />
    );
    fireEvent.click(screen.getByLabelText(/выбрать reel\.mp4/i));
    expect(onToggleChecked).toHaveBeenCalledWith("reel.mp4");
    expect(onSelect).not.toHaveBeenCalled();
    expect(screen.getByText(/выбрано: 1/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /скачать zip/i }));
    expect(onDownloadArchive).toHaveBeenCalled();
  });

  it("moves selection to the next video on j", () => {
    const onSelect = vi.fn();
    const second: VideoOut = {
      filename: "second.mp4",
      size_bytes: 1000,
      modified_at: new Date().toISOString(),
      media_type: "video",
      duration_sec: 20,
    };
    render(
      <MediaLibraryGrid
        {...baseProps}
        items={[items[0], second, items[1]]}
        selectedFilename="reel.mp4"
        onSelect={onSelect}
      />
    );
    fireEvent.keyDown(window, { key: "j" });
    expect(onSelect).toHaveBeenCalledWith(second);
  });
});
