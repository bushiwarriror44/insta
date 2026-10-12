import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AccountOut, PublicationOut, VideoOut } from "../../api/types";
import { ToastProvider } from "../../context/ToastContext";
import { byLabel } from "../../test/utils";
import { Publishing } from "../Publishing";

const apiMock = vi.hoisted(() => ({
  accounts: { list: vi.fn() },
  videos: {
    list: vi.fn(),
    upload: vi.fn(),
    remove: vi.fn(),
    download: vi.fn(),
    downloadArchive: vi.fn(),
  },
  jobs: { enqueue: vi.fn() },
  publications: { list: vi.fn(), refreshStats: vi.fn() },
  factory: {
    assets: vi.fn().mockResolvedValue([]),
    createGeneration: vi.fn(),
    createComposition: vi.fn(),
  },
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
  Object.values(apiMock.factory).forEach((fn) => fn.mockReset());
  apiMock.accounts.list.mockResolvedValue([account]);
  apiMock.videos.list.mockResolvedValue([video, image]);
  apiMock.publications.list.mockResolvedValue([publication]);
  apiMock.factory.assets.mockResolvedValue([]);
});

function renderPublishing(initialEntry = "/publishing") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <ToastProvider>
        <Publishing />
      </ToastProvider>
    </MemoryRouter>
  );
}

describe("Publishing page", () => {
  it("renders media library grid and publication statistics", async () => {
    renderPublishing();
    await screen.findAllByText("clip.mp4");
    fireEvent.click(screen.getByRole("button", { name: /вкладка фото/i }));
    expect((await screen.findAllByText("photo.jpg")).length).toBeGreaterThan(0);
    expect(screen.getByText("100 / 120")).toBeInTheDocument();
    expect(screen.getByText("CODE")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /вкладка видео/i })).toBeInTheDocument();
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
    await waitFor(() =>
      expect(apiMock.videos.upload).toHaveBeenCalledWith(
        file,
        expect.objectContaining({ compress: true })
      )
    );
    await screen.findByText(/загружено: new\.mp4/i);
  });

  it("uploads with compress=false when «Не сжимать» is checked", async () => {
    apiMock.videos.upload.mockResolvedValue({
      filename: "photo.jpg",
      size_bytes: 10,
      media_type: "image",
    });
    apiMock.videos.list
      .mockResolvedValueOnce([video, image])
      .mockResolvedValueOnce([video, image]);
    renderPublishing();
    await screen.findAllByText("clip.mp4");
    fireEvent.click(screen.getByLabelText(/не сжимать/i));
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File([new Uint8Array([1, 2, 3])], "photo.jpg", {
      type: "image/jpeg",
    });
    await userEvent.upload(input, file);
    fireEvent.click(screen.getByRole("button", { name: /^загрузить$/i }));
    await waitFor(() =>
      expect(apiMock.videos.upload).toHaveBeenCalledWith(
        file,
        expect.objectContaining({ compress: false })
      )
    );
  });

  it("continues batch upload after one file fails and shows progress queue", async () => {
    apiMock.videos.upload
      .mockRejectedValueOnce(new Error("NetworkError when attempting to fetch resource."))
      .mockResolvedValueOnce({
        filename: "ok.mp4",
        size_bytes: 4,
        media_type: "video",
      });
    apiMock.videos.list
      .mockResolvedValueOnce([video, image])
      .mockResolvedValueOnce([
        video,
        image,
        {
          filename: "ok.mp4",
          size_bytes: 4,
          modified_at: new Date().toISOString(),
          media_type: "video",
        },
      ]);
    renderPublishing();
    await screen.findAllByText("clip.mp4");
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const bad = new File([new Uint8Array([1])], "bad.mp4", { type: "video/mp4" });
    const good = new File([new Uint8Array([1, 2, 3, 4])], "ok.mp4", {
      type: "video/mp4",
    });
    await userEvent.upload(input, [bad, good]);
    fireEvent.click(screen.getByRole("button", { name: /^загрузить$/i }));

    await waitFor(() => expect(apiMock.videos.upload).toHaveBeenCalledTimes(2));
    expect(await screen.findByLabelText(/очередь загрузки/i)).toBeInTheDocument();
    expect(await screen.findByText(/загружено 1 из 2/i)).toBeInTheDocument();
    expect(screen.getByText("bad.mp4")).toBeInTheDocument();
    expect(screen.getByText("ok.mp4")).toBeInTheDocument();
  });

  it("downloads ZIP for checked media files", async () => {
    apiMock.videos.downloadArchive.mockResolvedValue(undefined);
    renderPublishing();
    await screen.findAllByText("clip.mp4");
    fireEvent.click(screen.getByLabelText(/выбрать clip\.mp4/i));
    fireEvent.click(screen.getByRole("button", { name: /скачать zip/i }));
    await waitFor(() =>
      expect(apiMock.videos.downloadArchive).toHaveBeenCalledWith(["clip.mp4"])
    );
  });

  it("downloads the selected preview file", async () => {
    apiMock.videos.download.mockResolvedValue(undefined);
    renderPublishing();
    await screen.findAllByText("clip.mp4");
    fireEvent.click(screen.getByRole("button", { name: /^скачать$/i }));
    await waitFor(() =>
      expect(apiMock.videos.download).toHaveBeenCalledWith("clip.mp4")
    );
  });

  it("enqueues a feed photo publication from preview panel", async () => {
    apiMock.jobs.enqueue.mockResolvedValue({});
    renderPublishing();
    await screen.findAllByText("clip.mp4");

    fireEvent.click(screen.getByRole("button", { name: /вкладка фото/i }));
    const photoCells = await screen.findAllByText("photo.jpg");
    fireEvent.click(photoCells[photoCells.length - 1]);
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

  it("quick publish uses the account selected in the preview panel", async () => {
    apiMock.accounts.list.mockResolvedValue([
      account,
      { ...account, id: 2, username: "bob" },
    ]);
    apiMock.jobs.enqueue.mockResolvedValue({});
    renderPublishing();
    await screen.findAllByText("clip.mp4");

    fireEvent.change(byLabel(/аккаунт/i), { target: { value: "bob" } });
    fireEvent.click(screen.getByRole("button", { name: /быстрая публикация clip\.mp4/i }));

    await waitFor(() =>
      expect(apiMock.jobs.enqueue).toHaveBeenCalledWith(
        expect.objectContaining({
          username: "bob",
          media_filename: "clip.mp4",
          post_type: "reel",
          when: null,
        })
      )
    );
  });

  it("after delete selects remaining media and syncs tab/post type", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    apiMock.videos.list.mockResolvedValue([video, image]);
    apiMock.videos.remove.mockImplementation(async () => {
      apiMock.videos.list.mockResolvedValue([image]);
    });

    renderPublishing();
    await screen.findAllByText("clip.mp4");
    await waitFor(() => expect(byLabel(/тип публикации/i)).toHaveValue("reel"));

    fireEvent.click(screen.getByRole("button", { name: /^удалить$/i }));

    await waitFor(() => expect(apiMock.videos.remove).toHaveBeenCalledWith("clip.mp4"));
    await waitFor(() => {
      expect(byLabel(/тип публикации/i)).toHaveValue("feed_photo");
    });
    expect(screen.getAllByText("photo.jpg").length).toBeGreaterThanOrEqual(1);
  });

  it("refreshes stats for a publication", async () => {
    const lastStatsAt = "2026-08-15T12:00:00.000Z";
    apiMock.publications.refreshStats.mockResolvedValue({
      ...publication,
      like_count: 11,
      last_stats_at: lastStatsAt,
    });
    renderPublishing();
    await screen.findByText("CODE");
    fireEvent.click(screen.getByRole("button", { name: /обновить статистику/i }));
    await waitFor(() =>
      expect(apiMock.publications.refreshStats).toHaveBeenCalledWith(10)
    );
    await screen.findByText("11");
    expect(
      screen.getByText(new Date(lastStatsAt).toLocaleString("ru-RU"))
    ).toBeInTheDocument();
  });

  it("shows generated fal assets in the library grid", async () => {
    apiMock.factory.assets.mockResolvedValue([
      {
        id: 3,
        filename: "fal-sunset.mp4",
        kind: "video",
        source: "fal",
        label: "sunset",
        prompt: "sunset",
        duration_s: 8,
        width: 1080,
        height: 1920,
        created_at: new Date().toISOString(),
      },
    ]);
    renderPublishing();
    expect((await screen.findAllByText("fal-sunset.mp4")).length).toBeGreaterThan(0);
  });

  it("reads library tab and media from the URL", async () => {
    renderPublishing("/publishing?tab=image&media=photo.jpg&username=alice");
    expect((await screen.findAllByText("photo.jpg")).length).toBeGreaterThan(0);
    expect(byLabel(/аккаунт/i)).toHaveValue("alice");
    expect(screen.getByRole("button", { name: /вкладка фото/i })).toHaveClass("bg-slate-800");
  });

  it("schedules a publication and links the toast to activity", async () => {
    apiMock.jobs.enqueue.mockResolvedValue({ id: 77 });
    renderPublishing();
    await screen.findAllByText("clip.mp4");
    fireEvent.change(byLabel(/запланировать на/i), {
      target: { value: "2026-09-10T12:00" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^запланировать$/i }));
    await waitFor(() =>
      expect(apiMock.jobs.enqueue).toHaveBeenCalledWith(
        expect.objectContaining({
          username: "alice",
          media_filename: "clip.mp4",
          when: expect.stringMatching(/^\d{4}-/),
        })
      )
    );
    const open = await screen.findByRole("link", { name: /открыть/i });
    expect(open).toHaveAttribute("href", "/activity?job=77");
    expect(screen.getByText(/публикация запланирована/i)).toBeInTheDocument();
  });

  it("queues a render and links the toast to renders", async () => {
    apiMock.factory.createGeneration.mockResolvedValue({ id: 9, status: "queued" });
    renderPublishing();
    await screen.findAllByText("clip.mp4");
    fireEvent.change(screen.getByPlaceholderText(/промпт для рендера/i), {
      target: { value: "sunset over the sea" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^рендер$/i }));
    await waitFor(() =>
      expect(apiMock.factory.createGeneration).toHaveBeenCalledWith({
        prompt: "sunset over the sea",
        backend: "auto",
      })
    );
    const open = await screen.findByRole("link", { name: /открыть/i });
    expect(open).toHaveAttribute("href", "/renders?gen=9");
  });
});
