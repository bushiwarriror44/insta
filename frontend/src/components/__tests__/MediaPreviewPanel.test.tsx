import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AccountOut, VideoOut } from "../../api/types";
import { fetchMediaObjectUrl } from "../../api/media";
import { MediaPreviewPanel } from "../MediaPreviewPanel";

vi.mock("../../api/media", () => ({
  fetchMediaObjectUrl: vi.fn(async () => "blob:mock-preview"),
  revokeMediaObjectUrl: vi.fn(),
  formatBytes: () => "1 KB",
  formatDuration: () => "1:00",
}));

const account: AccountOut = {
  id: 1,
  username: "alice",
  status: "active",
  proxy_id: 1,
  proxy_label: "p",
  proxy_country: null,
  proxy_geo_country: null,
  proxy_is_healthy: true,
  proxy_last_ip: null,
  timezone: "UTC",
  daily_post_cap: 3,
  min_gap_hours: 4,
  active_hour_start: 10,
  active_hour_end: 22,
  last_publish_at: null,
  last_idle_warmup_at: null,
  last_session_rotation_at: null,
  cooldown_until: null,
  caption_profile: null,
  has_totp: false,
  has_session_id: false,
  session_file_exists: false,
  session_source: "none",
  posts_today: 0,
  failures_today: 0,
};

const video: VideoOut = {
  filename: "clip.mp4",
  size_bytes: 1024,
  modified_at: new Date().toISOString(),
  media_type: "video",
  duration_sec: 60,
};

const image: VideoOut = {
  filename: "photo.jpg",
  size_bytes: 512,
  modified_at: new Date().toISOString(),
  media_type: "image",
};

const baseProps = {
  accounts: [account],
  accountId: 1,
  whenLocal: "",
  caption: "",
  saving: false,
  onAccountChange: () => {},
  onPostTypeChange: () => {},
  onWhenChange: () => {},
  onCaptionChange: () => {},
  onPublish: () => {},
  onDelete: () => {},
  onDownload: () => {},
};

describe("MediaPreviewPanel", () => {
  beforeEach(() => {
    vi.mocked(fetchMediaObjectUrl).mockReset();
    vi.mocked(fetchMediaObjectUrl).mockResolvedValue("blob:mock-preview");
  });

  it("shows empty state when no item selected", () => {
    render(<MediaPreviewPanel item={null} postType="reel" {...baseProps} />);
    expect(screen.getByText(/выберите видео или фото/i)).toBeInTheDocument();
  });

  it("renders video preview and publish button", async () => {
    const onPublish = vi.fn();
    const onDownload = vi.fn();
    render(
      <MediaPreviewPanel
        item={video}
        postType="reel"
        {...baseProps}
        onPublish={onPublish}
        onDownload={onDownload}
      />
    );
    expect(screen.getByText("clip.mp4")).toBeInTheDocument();
    await waitFor(() => expect(document.querySelector("video")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /опубликовать сейчас/i }));
    expect(onPublish).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /^скачать$/i }));
    expect(onDownload).toHaveBeenCalled();
  });

  it("shows title fields for YouTube Shorts", () => {
    render(<MediaPreviewPanel item={video} postType="youtube_short" {...baseProps} />);
    expect(screen.getByText("Заголовок")).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/shorts/i)).toBeInTheDocument();
    expect(screen.getByText("Описание")).toBeInTheDocument();
    expect(screen.getByText("Теги")).toBeInTheDocument();
  });

  it("clears stale preview blob when switching files", async () => {
    let resolveImage: (url: string) => void = () => {};
    vi.mocked(fetchMediaObjectUrl)
      .mockResolvedValueOnce("blob:video")
      .mockImplementationOnce(
        () =>
          new Promise<string>((resolve) => {
            resolveImage = resolve;
          })
      );

    const { rerender } = render(
      <MediaPreviewPanel item={video} postType="reel" {...baseProps} />
    );
    await waitFor(() => {
      const el = document.querySelector("video");
      expect(el).toBeTruthy();
      expect(el?.getAttribute("src")).toBe("blob:video");
    });

    rerender(<MediaPreviewPanel item={image} postType="feed_photo" {...baseProps} />);

    expect(screen.getByText(/предпросмотр недоступен/i)).toBeInTheDocument();
    expect(document.querySelector("video")).toBeNull();
    expect(document.querySelector("img")).toBeNull();

    resolveImage("blob:image");
    await waitFor(() => {
      const el = document.querySelector("img");
      expect(el).toBeTruthy();
      expect(el?.getAttribute("src")).toBe("blob:image");
    });
  });
});
