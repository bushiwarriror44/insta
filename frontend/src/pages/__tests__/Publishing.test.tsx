import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AccountOut, PublicationOut, VideoOut } from "../../api/types";
import { ToastProvider } from "../../context/ToastContext";
import { byLabel } from "../../test/utils";
import { Publishing } from "../Publishing";

const apiMock = vi.hoisted(() => ({
  accounts: { list: vi.fn() },
  videos: { list: vi.fn(), upload: vi.fn(), remove: vi.fn() },
  jobs: { enqueue: vi.fn() },
  publications: { list: vi.fn(), refreshStats: vi.fn() },
}));

vi.mock("../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../api/client")>(
    "../../api/client"
  );
  return {
    ...actual,
    api: apiMock,
  };
});

vi.mock("../../api/media", () => ({
  fetchMediaObjectUrl: vi.fn(async () => "blob:mock-preview"),
  revokeMediaObjectUrl: vi.fn(),
  formatBytes: (n: number) => `${n} B`,
  formatDuration: () => "0:12",
  mediaApiPath: (f: string) => `/api/videos/${f}`,
}));

const account: AccountOut = {
  id: 1,
  username: "alice",
  status: "active",
  proxy_id: 1,
  proxy_label: "res-1",
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
  duration_sec: 12,
};

const image: VideoOut = {
  filename: "photo.jpg",
  size_bytes: 512,
  modified_at: new Date().toISOString(),
  media_type: "image",
};

const publication: PublicationOut = {
  id: 10,
  job_id: 20,
  account_id: 1,
  account_username: "alice",
  post_type: "reel",
  media_id: "MID",
  media_code: "CODE",
  final_media_path: "data/videos/out/clip.mp4",
  final_caption: "cap",
  success: true,
  error: null,
  view_count: 100,
  like_count: 10,
  comment_count: 2,
  play_count: 120,
  save_count: null,
  share_count: null,
  last_stats_at: null,
  created_at: new Date().toISOString(),
};

beforeEach(() => {
  Object.values(apiMock.accounts).forEach((fn) => fn.mockReset());
  Object.values(apiMock.videos).forEach((fn) => fn.mockReset());
  Object.values(apiMock.jobs).forEach((fn) => fn.mockReset());
  Object.values(apiMock.publications).forEach((fn) => fn.mockReset());
  apiMock.accounts.list.mockResolvedValue([account]);
  apiMock.videos.list.mockResolvedValue([video, image]);
  apiMock.publications.list.mockResolvedValue([publication]);
});

function renderPublishing() {
  return render(
    <ToastProvider>
      <Publishing />
    </ToastProvider>
  );
}

describe("Publishing page", () => {
  it("renders media library grid and publication statistics", async () => {
    renderPublishing();
    await screen.findAllByText("clip.mp4");
    fireEvent.click(screen.getByRole("button", { name: /^фото$/i }));
    expect(screen.getByText("photo.jpg")).toBeInTheDocument();
    expect(screen.getByText("100 / 120")).toBeInTheDocument();
    expect(screen.getByText("CODE")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /видео/i })).toBeInTheDocument();
  });

  it("uploads a media file after staging confirm", async () => {
    apiMock.videos.upload.mockResolvedValue({
      filename: "new.mp4",
      size_bytes: 4,
      media_type: "video",
    });
    apiMock.videos.list.mockResolvedValueOnce([video, image]).mockResolvedValueOnce([
      video,
      image,
      {
        filename: "new.mp4",
        size_bytes: 4,
        modified_at: new Date().toISOString(),
        media_type: "video",
      },
    ]);
    renderPublishing();
    await screen.findAllByText("clip.mp4");
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File([new Uint8Array([1, 2, 3, 4])], "new.mp4", {
      type: "video/mp4",
    });
    await userEvent.upload(input, file);
    fireEvent.click(screen.getByRole("button", { name: /^загрузить$/i }));
    await waitFor(() => expect(apiMock.videos.upload).toHaveBeenCalledWith(file));
    await screen.findByText(/загружено: new\.mp4/i);
  });

  it("enqueues a feed photo publication from preview panel", async () => {
    apiMock.jobs.enqueue.mockResolvedValue({});
    renderPublishing();
    await screen.findAllByText("clip.mp4");

    fireEvent.click(screen.getByRole("button", { name: /^фото$/i }));
    fireEvent.click(screen.getByText("photo.jpg"));
    fireEvent.change(byLabel(/подпись/i), { target: { value: "hello" } });
    fireEvent.click(screen.getByRole("button", { name: /опубликовать сейчас/i }));

    await waitFor(() =>
      expect(apiMock.jobs.enqueue).toHaveBeenCalledWith(
        expect.objectContaining({
          username: "alice",
          media_filename: "photo.jpg",
          post_type: "feed_photo",
          caption_template: "hello",
          when: null,
        })
      )
    );
  });

  it("quick publish from library card", async () => {
    apiMock.jobs.enqueue.mockResolvedValue({});
    renderPublishing();
    await screen.findAllByText("clip.mp4");
    fireEvent.click(screen.getByRole("button", { name: /быстрая публикация clip\.mp4/i }));
    await waitFor(() =>
      expect(apiMock.jobs.enqueue).toHaveBeenCalledWith(
        expect.objectContaining({
          username: "alice",
          media_filename: "clip.mp4",
          post_type: "reel",
          when: null,
        })
      )
    );
  });

  it("refreshes stats for a publication", async () => {
    apiMock.publications.refreshStats.mockResolvedValue({
      ...publication,
      like_count: 11,
      last_stats_at: new Date().toISOString(),
    });
    renderPublishing();
    await screen.findByText("CODE");
    fireEvent.click(screen.getByRole("button", { name: /обновить статистику/i }));
    await waitFor(() =>
      expect(apiMock.publications.refreshStats).toHaveBeenCalledWith(10)
    );
    await screen.findByText("11");
  });
});
