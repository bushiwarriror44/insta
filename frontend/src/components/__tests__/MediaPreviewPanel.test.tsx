import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AccountOut, VideoOut } from "../../api/types";
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
  session_file_updated_at: null,
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

describe("MediaPreviewPanel", () => {
  it("shows empty state when no item selected", () => {
    render(
      <MediaPreviewPanel
        item={null}
        accounts={[account]}
        username="alice"
        postType="reel"
        whenLocal=""
        caption=""
        saving={false}
        onUsernameChange={() => {}}
        onPostTypeChange={() => {}}
        onWhenChange={() => {}}
        onCaptionChange={() => {}}
        onPublish={() => {}}
        onDelete={() => {}}
        onDownload={() => {}}
      />
    );
    expect(screen.getByText(/выберите видео или фото/i)).toBeInTheDocument();
  });

  it("renders video preview and publish button", async () => {
    const onPublish = vi.fn();
    const onDownload = vi.fn();
    render(
      <MediaPreviewPanel
        item={video}
        accounts={[account]}
        username="alice"
        postType="reel"
        whenLocal=""
        caption=""
        saving={false}
        onUsernameChange={() => {}}
        onPostTypeChange={() => {}}
        onWhenChange={() => {}}
        onCaptionChange={() => {}}
        onPublish={onPublish}
        onDelete={() => {}}
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
});
