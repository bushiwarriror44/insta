import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useSearchParams } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../../api/client";
import type { JobOut } from "../../api/types";
import { Calendar } from "../Calendar";

vi.mock("../../api/client", () => ({
  api: {
    jobs: { list: vi.fn().mockResolvedValue([]), reschedule: vi.fn() },
  },
  formatApiError: (err: unknown) => String(err),
}));

vi.mock("../../context/ToastContext", () => ({
  useToast: () => ({ push: vi.fn() }),
}));

function mondayOfCurrentWeek(): Date {
  const now = new Date();
  const day = now.getDay();
  const mondayOffset = day === 0 ? -6 : 1 - day;
  const start = new Date(now);
  start.setHours(0, 0, 0, 0);
  start.setDate(start.getDate() + mondayOffset);
  return start;
}

function dayKey(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${dd}`;
}

const job: JobOut = {
  id: 9,
  account_id: 1,
  account_username: "alice",
  source_video_path: "/a.mp4",
  post_type: "reel",
  caption_template: null,
  scheduled_for: new Date(mondayOfCurrentWeek().getTime() + 15 * 3600000).toISOString(),
  status: "queued",
  attempts: 0,
  last_error: null,
  next_attempt_at: null,
  started_at: null,
  finished_at: null,
  created_at: new Date().toISOString(),
};

function ActivityProbe() {
  const [params] = useSearchParams();
  return <div>job logs {params.get("job")}</div>;
}

function renderCalendar() {
  return render(
    <MemoryRouter>
      <Routes>
        <Route path="/" element={<Calendar />} />
        <Route path="/activity" element={<ActivityProbe />} />
      </Routes>
    </MemoryRouter>
  );
}

describe("Calendar page", () => {
  beforeEach(() => {
    vi.mocked(api.jobs.list).mockReset();
    vi.mocked(api.jobs.reschedule).mockReset();
    vi.mocked(api.jobs.list).mockResolvedValue([]);
    vi.mocked(api.jobs.reschedule).mockResolvedValue({} as never);
  });

  it("renders the week heading", async () => {
    renderCalendar();
    expect(await screen.findByRole("heading", { name: /календарь/i })).toBeInTheDocument();
  });

  it("moves the week with next and restores today", async () => {
    renderCalendar();
    const weekLabel = () => screen.getByText(/неделя с/i).textContent;
    await screen.findByRole("button", { name: /вперёд/i });
    const initial = weekLabel();
    fireEvent.click(screen.getByRole("button", { name: /вперёд/i }));
    expect(weekLabel()).not.toBe(initial);
    fireEvent.click(screen.getByRole("button", { name: /сегодня/i }));
    expect(weekLabel()).toBe(initial);
  });

  it("keeps the original hour when a slot is dropped on another day", async () => {
    vi.mocked(api.jobs.list).mockResolvedValue([job]);
    renderCalendar();
    const card = await screen.findByText("alice");
    fireEvent.dragStart(card.closest("[draggable]") as HTMLElement);

    const tuesday = new Date(mondayOfCurrentWeek());
    tuesday.setDate(tuesday.getDate() + 1);
    fireEvent.drop(screen.getByTestId(`calendar-day-${dayKey(tuesday)}`));

    await waitFor(() => expect(api.jobs.reschedule).toHaveBeenCalled());
    const sent = new Date(vi.mocked(api.jobs.reschedule).mock.calls[0][1] as string);
    const original = new Date(job.scheduled_for);
    expect(sent.getHours()).toBe(original.getHours());
    expect(sent.getMinutes()).toBe(original.getMinutes());
    expect(dayKey(sent)).toBe(dayKey(tuesday));
  });

  it("opens activity logs when a slot is clicked", async () => {
    vi.mocked(api.jobs.list).mockResolvedValue([job]);
    renderCalendar();
    fireEvent.click(await screen.findByText("alice"));
    expect(await screen.findByText(/job logs 9/i)).toBeInTheDocument();
  });

  it("still opens activity logs after a cancelled drag", async () => {
    vi.mocked(api.jobs.list).mockResolvedValue([job]);
    renderCalendar();
    const card = (await screen.findByText("alice")).closest("[draggable]") as HTMLElement;
    fireEvent.dragStart(card);
    fireEvent.dragEnd(card);
    fireEvent.click(card);
    expect(await screen.findByText(/job logs 9/i)).toBeInTheDocument();
  });
});
