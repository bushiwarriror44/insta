import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../../context/ToastContext";
import type { AccountOut, VideoOut } from "../../api/types";
import { Upload } from "../Upload";

const apiMock = vi.hoisted(() => ({
  accounts: { list: vi.fn() },
  videos: { list: vi.fn(), upload: vi.fn(), remove: vi.fn() },
  jobs: { enqueue: vi.fn() },
  publications: { list: vi.fn() },
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
};

beforeEach(() => {
  apiMock.accounts.list.mockReset();
  apiMock.videos.list.mockReset();
  apiMock.videos.upload.mockReset();
  apiMock.videos.remove.mockReset();
  apiMock.jobs.enqueue.mockReset();
  apiMock.publications.list.mockReset();
  apiMock.accounts.list.mockResolvedValue([account]);
  apiMock.videos.list.mockResolvedValue([video]);
  apiMock.publications.list.mockResolvedValue([]);
});

function renderUpload() {
  return render(
    <MemoryRouter>
      <ToastProvider>
        <Upload />
      </ToastProvider>
    </MemoryRouter>
  );
}

describe("Upload page (library alias)", () => {
  it("renders library grid after load", async () => {
    renderUpload();
    expect(await screen.findAllByText("clip.mp4")).not.toHaveLength(0);
    expect(screen.getByRole("heading", { name: /^библиотека$/i })).toBeInTheDocument();
  });

  it("uploads a file via staging drop zone", async () => {
    apiMock.videos.upload.mockResolvedValue({
      filename: "uploaded.mp4",
      size_bytes: 4,
      media_type: "video",
    });
    apiMock.videos.list.mockResolvedValueOnce([video]).mockResolvedValueOnce([
      video,
      {
        filename: "uploaded.mp4",
        size_bytes: 4,
        modified_at: new Date().toISOString(),
        media_type: "video",
      },
    ]);

    renderUpload();
    await screen.findAllByText("clip.mp4");

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File([new Uint8Array([1, 2, 3, 4])], "uploaded.mp4", {
      type: "video/mp4",
    });
    await userEvent.upload(input, file);
    fireEvent.click(screen.getByRole("button", { name: /^загрузить$/i }));

    await waitFor(() =>
      expect(apiMock.videos.upload).toHaveBeenCalledWith(
        file,
        expect.objectContaining({ compress: true })
      )
    );
    await screen.findByText(/загружено: uploaded\.mp4/i);
  });

  it("enqueues a job ASAP from preview panel", async () => {
    apiMock.jobs.enqueue.mockResolvedValue({});
    renderUpload();
    await screen.findAllByText("clip.mp4");

    fireEvent.click(screen.getByRole("button", { name: /опубликовать сейчас/i }));

    await waitFor(() =>
      expect(apiMock.jobs.enqueue).toHaveBeenCalledWith(
        expect.objectContaining({
          username: "alice",
          media_filename: "clip.mp4",
          when: null,
        })
      )
    );
  });

  it("removes a video after confirm from preview panel", async () => {
    apiMock.videos.remove.mockResolvedValue(undefined);
    vi.spyOn(window, "confirm").mockReturnValue(true);

    renderUpload();
    await screen.findAllByText("clip.mp4");

    fireEvent.click(screen.getByRole("button", { name: /^удалить$/i }));

    await waitFor(() =>
      expect(apiMock.videos.remove).toHaveBeenCalledWith("clip.mp4")
    );
  });
});
