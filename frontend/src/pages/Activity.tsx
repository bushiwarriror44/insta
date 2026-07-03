import { Ban, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import { Card } from "../components/Card";
import { Loader } from "../components/Loader";
import { StatusBadge } from "../components/StatusBadge";
import { useToast } from "../context/ToastContext";
import type { EventOut, JobOut } from "../api/types";

const POLL_INTERVAL_MS = 7000;

const JOB_STATUSES = ["", "queued", "running", "done", "failed", "dead", "cancelled"];
const EVENT_LEVELS = ["", "info", "warn", "error", "critical"];

export function Activity() {
  const { push } = useToast();
  const [jobs, setJobs] = useState<JobOut[]>([]);
  const [events, setEvents] = useState<EventOut[]>([]);
  const [jobStatus, setJobStatus] = useState<string>("");
  const [eventLevel, setEventLevel] = useState<string>("");
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    const [j, e] = await Promise.all([
      api.jobs.list({ status: jobStatus || undefined, limit: 100 }),
      api.events.list({ level: eventLevel || undefined, limit: 100 }),
    ]);
    setJobs(j);
    setEvents(e);
  }, [jobStatus, eventLevel]);

  useEffect(() => {
    let cancelled = false;
    let initial = true;
    async function tick() {
      try {
        await reload();
      } catch (err) {
        if (initial) push((err as Error).message, "error");
      } finally {
        if (initial) setLoading(false);
        initial = false;
      }
      if (cancelled) return;
    }
    tick();
    const id = window.setInterval(tick, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [reload, push]);

  if (loading) return <Loader />;

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold">Activity</h1>
          <p className="text-sm text-slate-400 mt-1">
            Live job queue and event log. Refreshes every {POLL_INTERVAL_MS / 1000}s.
          </p>
        </div>
        <button
          className="btn-ghost"
          onClick={async () => {
            try {
              await reload();
              push("Refreshed", "info");
            } catch (err) {
              push((err as Error).message, "error");
            }
          }}
        >
          <RefreshCw size={16} /> Refresh now
        </button>
      </div>

      <Card
        title="Jobs"
        description={`${jobs.length} latest`}
        actions={
          <select
            className="input max-w-[140px] py-1.5 text-xs"
            value={jobStatus}
            onChange={(e) => setJobStatus(e.target.value)}
          >
            {JOB_STATUSES.map((s) => (
              <option key={s} value={s}>
                {s ? s : "All statuses"}
              </option>
            ))}
          </select>
        }
      >
        {jobs.length === 0 ? (
          <div className="text-sm text-slate-500">No jobs match the filter.</div>
        ) : (
          <div className="overflow-x-auto -mx-5">
            <table className="table-base">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Account</th>
                  <th>Status</th>
                  <th>Scheduled</th>
                  <th>Attempts</th>
                  <th>Source</th>
                  <th>Last error</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((j) => (
                  <tr key={j.id} className="hover:bg-slate-900/40 align-top">
                    <td className="tabular-nums text-slate-400">#{j.id}</td>
                    <td className="font-medium">
                      {j.account_username ? `@${j.account_username}` : `id:${j.account_id}`}
                    </td>
                    <td>
                      <StatusBadge value={j.status} />
                    </td>
                    <td className="text-xs text-slate-400">
                      {new Date(j.scheduled_for).toLocaleString()}
                    </td>
                    <td className="tabular-nums text-slate-300">{j.attempts}</td>
                    <td className="text-xs text-slate-400 max-w-[260px] break-all">
                      {j.source_video_path.split(/[\\/]/).pop()}
                    </td>
                    <td className="text-xs text-rose-300 max-w-[280px] break-words">
                      {j.last_error ?? ""}
                    </td>
                    <td className="text-right">
                      {(j.status === "queued" || j.status === "failed") && (
                        <button
                          className="btn-ghost text-xs"
                          onClick={async () => {
                            try {
                              const upd = await api.jobs.cancel(j.id);
                              setJobs((arr) =>
                                arr.map((x) => (x.id === upd.id ? upd : x))
                              );
                              push(`Job #${j.id} cancelled`, "info");
                            } catch (err) {
                              push((err as Error).message, "error");
                            }
                          }}
                        >
                          <Ban size={14} /> Cancel
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card
        title="Events"
        description={`${events.length} latest`}
        actions={
          <select
            className="input max-w-[140px] py-1.5 text-xs"
            value={eventLevel}
            onChange={(e) => setEventLevel(e.target.value)}
          >
            {EVENT_LEVELS.map((l) => (
              <option key={l} value={l}>
                {l ? l : "All levels"}
              </option>
            ))}
          </select>
        }
      >
        {events.length === 0 ? (
          <div className="text-sm text-slate-500">No events.</div>
        ) : (
          <ul className="divide-y divide-slate-800">
            {events.map((ev) => (
              <li key={ev.id} className="flex items-start gap-3 py-3 text-sm">
                <StatusBadge value={ev.level} />
                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-baseline gap-2">
                    <span className="font-medium">{ev.kind}</span>
                    {ev.account_username && (
                      <span className="text-slate-400 text-xs">@{ev.account_username}</span>
                    )}
                    <span className="ml-auto text-xs text-slate-500">
                      {new Date(ev.created_at).toLocaleString()}
                    </span>
                  </div>
                  <div className="text-slate-300 mt-0.5 break-words">{ev.message}</div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
