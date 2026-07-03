import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../../context/ToastContext";
import type { EventOut, JobOut } from "../../api/types";
import { Activity } from "../Activity";

const apiMock = vi.hoisted(() => ({
  jobs: { list: vi.fn(), cancel: vi.fn() },
  events: { list: vi.fn() },
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

const job: JobOut = {
  id: 42,
  account_id: 1,
  account_username: "alice",
  source_video_path: "/data/videos/source/clip.mp4",
  post_type: "reel",
  caption_template: null,
  scheduled_for: new Date().toISOString(),
  status: "queued",
  attempts: 0,
  last_error: null,
  started_at: null,
  finished_at: null,
  created_at: new Date().toISOString(),
};

const event: EventOut = {
  id: 5,
  account_id: 1,
  account_username: "alice",
  level: "warn",
  kind: "challenge",
  message: "code requested",
  created_at: new Date().toISOString(),
};

beforeEach(() => {
  apiMock.jobs.list.mockReset();
  apiMock.jobs.cancel.mockReset();
  apiMock.events.list.mockReset();
  apiMock.jobs.list.mockResolvedValue([job]);
  apiMock.events.list.mockResolvedValue([event]);
});

function renderActivity() {
  return render(
    <ToastProvider>
      <Activity />
    </ToastProvider>
  );
}

describe("Activity page", () => {
  it("renders jobs and events tables", async () => {
    renderActivity();
    await screen.findByText("#42");
    // @alice and "queued"/"challenge" can match in multiple sections (rows + select options).
    expect(screen.getAllByText("@alice").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("queued").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("challenge")).toBeInTheDocument();
    expect(screen.getByText("code requested")).toBeInTheDocument();
  });

  it("filters jobs by status when the dropdown changes", async () => {
    renderActivity();
    await screen.findByText("#42");
    apiMock.jobs.list.mockClear();

    const select = screen.getAllByRole("combobox")[0];
    fireEvent.change(select, { target: { value: "running" } });

    await waitFor(() =>
      expect(apiMock.jobs.list).toHaveBeenCalledWith(
        expect.objectContaining({ status: "running", limit: 100 })
      )
    );
  });

  it("filters events by level", async () => {
    renderActivity();
    await screen.findByText("#42");
    apiMock.events.list.mockClear();

    const selects = screen.getAllByRole("combobox");
    fireEvent.change(selects[1], { target: { value: "error" } });

    await waitFor(() =>
      expect(apiMock.events.list).toHaveBeenCalledWith(
        expect.objectContaining({ level: "error", limit: 100 })
      )
    );
  });

  it("cancels a queued job from the table", async () => {
    apiMock.jobs.cancel.mockResolvedValue({ ...job, status: "cancelled" });
    renderActivity();
    await screen.findByText("#42");

    const cancelBtn = screen.getByRole("button", { name: /^cancel$/i });
    fireEvent.click(cancelBtn);
    await waitFor(() => expect(apiMock.jobs.cancel).toHaveBeenCalledWith(42));
  });

  it("does not show cancel button for terminal job statuses", async () => {
    apiMock.jobs.list.mockResolvedValue([{ ...job, status: "done" }]);
    renderActivity();
    await screen.findByText("#42");
    expect(
      screen.queryByRole("button", { name: /^cancel$/i })
    ).not.toBeInTheDocument();
  });

  it("renders empty placeholder when there are no jobs", async () => {
    apiMock.jobs.list.mockResolvedValue([]);
    apiMock.events.list.mockResolvedValue([]);
    renderActivity();
    await screen.findByText(/no jobs match the filter/i);
    expect(screen.getByText(/no events\b/i)).toBeInTheDocument();
  });
});
