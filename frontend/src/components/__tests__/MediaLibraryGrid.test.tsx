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

describe("MediaLibraryGrid", () => {
  it("renders video cards and calls onSelect", () => {
    const onSelect = vi.fn();
    render(
      <MediaLibraryGrid
        items={items}
        selectedFilename="reel.mp4"
        tab="video"
        search=""
        onTabChange={() => {}}
        onSearchChange={() => {}}
        onSelect={onSelect}
        onQuickPublish={() => {}}
      />
    );
    expect(screen.getByText("reel.mp4")).toBeInTheDocument();
    fireEvent.click(screen.getByText("reel.mp4"));
    expect(onSelect).toHaveBeenCalledWith(items[0]);
  });

  it("calls onQuickPublish from card button", () => {
    const onQuickPublish = vi.fn();
    render(
      <MediaLibraryGrid
        items={items}
        selectedFilename={null}
        tab="video"
        search=""
        onTabChange={() => {}}
        onSearchChange={() => {}}
        onSelect={() => {}}
        onQuickPublish={onQuickPublish}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /quick publish reel\.mp4/i }));
    expect(onQuickPublish).toHaveBeenCalledWith(items[0]);
  });
});
