import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { showAssistant } from "../lib/uiEvents";
import type { AccountOut, JobOut, VideoOut } from "../api/types";

interface Command {
  label: string;
  hint: string;
  go: () => void;
}

const PAGES: { label: string; to: string }[] = [
  { label: "Панель", to: "/" },
  { label: "Аккаунты", to: "/accounts" },
  { label: "Библиотека", to: "/publishing" },
  { label: "Агент", to: "/agent" },
  { label: "Рендеры", to: "/renders" },
  { label: "Календарь", to: "/calendar" },
  { label: "Активность", to: "/activity" },
  { label: "Обслуживание", to: "/maintenance" },
];

const OWNER_PAGES: { label: string; to: string }[] = [
  { label: "Доступы", to: "/operators" },
  { label: "Настройки", to: "/settings" },
];

export function CommandPalette({ onClose }: { onClose: () => void }) {
  const { role } = useAuth();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [accounts, setAccounts] = useState<AccountOut[]>([]);
  const [jobs, setJobs] = useState<JobOut[]>([]);
  const [clips, setClips] = useState<VideoOut[]>([]);
  const navigate = useNavigate();

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const rows = (await api.accounts.list()) ?? [];
        if (!cancelled) setAccounts(rows);
      } catch {
        if (!cancelled) setAccounts([]);
      }
      try {
        const [queued, failed] = await Promise.all([
          api.jobs.list({ status: "queued", limit: 20 }),
          api.jobs.list({ status: "failed", limit: 20 }),
        ]);
        if (!cancelled) setJobs([...(queued ?? []), ...(failed ?? [])]);
      } catch {
        if (!cancelled) setJobs([]);
      }
      try {
        const rows = (await api.videos.list()) ?? [];
        if (!cancelled) setClips(rows);
      } catch {
        if (!cancelled) setClips([]);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const commands = useMemo<Command[]>(() => {
    const pages = role === "owner" ? [...PAGES, ...OWNER_PAGES] : PAGES;
    const all: Command[] = pages.map((page) => ({
      label: page.label,
      hint: "страница",
      go: () => navigate(page.to),
    }));
    all.push({
      label: "Спросить агента",
      hint: "чат",
      go: () => showAssistant(),
    });
    all.push({
      label: "Снять копию базы",
      hint: "обслуживание",
      go: () => navigate("/maintenance"),
    });
    for (const account of accounts) {
      all.push({
        label: `@${account.username}`,
        hint: `аккаунт · ${account.platform || "instagram"}`,
        go: () => navigate(`/accounts?username=${encodeURIComponent(account.username)}`),
      });
    }
    for (const job of jobs) {
      all.push({
        label: `#${job.id} ${job.title || job.account_username || ""}`.trim(),
        hint: `задача · ${job.status}`,
        go: () => navigate(`/activity?job=${job.id}`),
      });
    }
    for (const clip of clips.slice(0, 30)) {
      all.push({
        label: clip.filename,
        hint: "клип",
        go: () => navigate("/publishing"),
      });
    }
    const needle = query.trim().toLowerCase();
    if (!needle) return all;
    return all.filter(
      (c) =>
        c.label.toLowerCase().includes(needle) || c.hint.toLowerCase().includes(needle)
    );
  }, [accounts, clips, jobs, navigate, query, role]);

  useEffect(() => setActive(0), [query, commands.length]);

  const run = (command: Command | undefined) => {
    if (!command) return;
    command.go();
    onClose();
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/70 p-4 pt-24 backdrop-blur-sm"
      onClick={onClose}
      data-testid="palette-backdrop"
    >
      <div
        role="dialog"
        aria-label="Перейти куда угодно"
        className="w-full max-w-lg overflow-hidden rounded-xl border border-slate-800 bg-slate-950 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <input
          autoFocus
          aria-label="Куда перейти"
          className="input w-full rounded-none border-0 border-b border-slate-800 bg-transparent"
          placeholder="Страница, аккаунт, задача…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setActive((n) => Math.min(n + 1, Math.max(commands.length - 1, 0)));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setActive((n) => Math.max(n - 1, 0));
            } else if (e.key === "Enter") {
              e.preventDefault();
              run(commands[active]);
            } else if (e.key === "Escape") {
              onClose();
            }
          }}
        />
        <ul className="max-h-80 overflow-y-auto py-1">
          {commands.length === 0 ? (
            <li className="px-4 py-3 text-sm text-slate-500">Ничего с таким названием.</li>
          ) : (
            commands.map((command, i) => (
              <li key={`${command.hint}-${command.label}`}>
                <button
                  type="button"
                  className={`flex w-full items-center justify-between px-4 py-2 text-left text-sm ${
                    i === active ? "bg-slate-800/80" : "hover:bg-slate-900/60"
                  }`}
                  onMouseEnter={() => setActive(i)}
                  onClick={() => run(command)}
                >
                  <span>{command.label}</span>
                  <span className="text-xs text-slate-500">{command.hint}</span>
                </button>
              </li>
            ))
          )}
        </ul>
      </div>
    </div>
  );
}
