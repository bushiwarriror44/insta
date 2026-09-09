import {
  CalendarDays,
  Clapperboard,
  Sparkles,
  Activity as ActivityIcon,
  KeyRound,
  LayoutDashboard,
  Library,
  LogOut,
  Settings as SettingsIcon,
  Users,
  Wrench,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import clsx from "clsx";

import { api } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { useHotkeys } from "../hooks/useHotkeys";
import { usePollWhenVisible } from "../hooks/usePollWhenVisible";
import { focusPageSearch, REFRESH_NAV_BADGES, showAssistant } from "../lib/uiEvents";
import { AgentToggle } from "./AgentToggle";
import { Assistant } from "./Assistant";
import { CommandPalette } from "./CommandPalette";
import { Modal } from "./Modal";

const NAV = [
  { to: "/", label: "Панель", icon: LayoutDashboard, end: true, testId: "nav-dashboard" },
  { to: "/accounts", label: "Аккаунты", icon: Users, testId: "nav-accounts" },
  { to: "/publishing", label: "Библиотека", icon: Library, testId: "nav-publishing" },
  { to: "/agent", label: "Агент", icon: Sparkles, testId: "nav-agent", badge: "questions" as const },
  { to: "/renders", label: "Рендеры", icon: Clapperboard, testId: "nav-renders" },
  { to: "/calendar", label: "Календарь", icon: CalendarDays, testId: "nav-calendar" },
  { to: "/activity", label: "Активность", icon: ActivityIcon, testId: "nav-activity", badge: "review" as const },
  { to: "/maintenance", label: "Обслуживание", icon: Wrench, testId: "nav-maintenance" },
];

type Badges = { review: number; failed: number; questions: number };

export function Layout() {
  const { state, logout, authRequired, role } = useAuth();
  const isAuthed = state.state === "authed";
  const isOwner = role === "owner";
  const [dockHidden, setDockHidden] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [badges, setBadges] = useState<Badges>({ review: 0, failed: 0, questions: 0 });

  const loadBadges = useCallback(async () => {
    try {
      const summary = await api.dashboard();
      setBadges({
        review: summary.jobs_awaiting_review ?? 0,
        failed: summary.jobs_failed_24h ?? 0,
        questions: summary.open_questions ?? 0,
      });
    } catch {
      /* nav badges stay on last known */
    }
  }, []);

  usePollWhenVisible(loadBadges, 15000);

  useEffect(() => {
    window.addEventListener(REFRESH_NAV_BADGES, loadBadges);
    return () => window.removeEventListener(REFRESH_NAV_BADGES, loadBadges);
  }, [loadBadges]);

  const hotkeys = useMemo(
    () => ({
      "mod+k": (event: KeyboardEvent) => {
        event.preventDefault();
        setPaletteOpen(true);
      },
      "/": (event: KeyboardEvent) => {
        event.preventDefault();
        if (!focusPageSearch()) setPaletteOpen(true);
      },
      c: (event: KeyboardEvent) => {
        event.preventDefault();
        showAssistant();
      },
      "?": (event: KeyboardEvent) => {
        event.preventDefault();
        setHelpOpen(true);
      },
    }),
    []
  );

  useHotkeys(hotkeys, !paletteOpen && !helpOpen);

  return (
    <div className="min-h-screen flex bg-slate-950 text-slate-100">
      <aside className="w-60 shrink-0 border-r border-slate-800 bg-slate-900/40 flex flex-col">
        <div className="px-5 py-5 border-b border-slate-800">
          <div className="text-lg font-semibold tracking-tight">Reels Admin</div>
          <div className="text-xs text-slate-500 mt-0.5">Instagram · YouTube · TikTok</div>
        </div>
        <nav className="flex-1 px-3 py-4 space-y-1">
          {NAV.map(({ to, label, icon: Icon, end, testId, badge }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              data-testid={testId}
              className={({ isActive }) =>
                clsx(
                  "flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors",
                  isActive
                    ? "bg-brand-500/15 text-brand-200"
                    : "text-slate-300 hover:bg-slate-800/60 hover:text-white"
                )
              }
            >
              <Icon size={18} />
              <span className="flex-1">{label}</span>
              {badge === "review" && badges.review > 0 ? (
                <NavBadge count={badges.review} />
              ) : null}
              {badge === "questions" && badges.questions > 0 ? (
                <NavBadge count={badges.questions} />
              ) : null}
            </NavLink>
          ))}
          {isOwner ? (
            <>
              <NavLink
                to="/operators"
                data-testid="nav-operators"
                className={({ isActive }) =>
                  clsx(
                    "flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors",
                    isActive
                      ? "bg-brand-500/15 text-brand-200"
                      : "text-slate-300 hover:bg-slate-800/60 hover:text-white"
                  )
                }
              >
                <KeyRound size={18} />
                <span>Доступы</span>
              </NavLink>
              <NavLink
                to="/settings"
                data-testid="nav-settings"
                className={({ isActive }) =>
                  clsx(
                    "flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors",
                    isActive
                      ? "bg-brand-500/15 text-brand-200"
                      : "text-slate-300 hover:bg-slate-800/60 hover:text-white"
                  )
                }
              >
                <SettingsIcon size={18} />
                <span>Настройки</span>
              </NavLink>
            </>
          ) : null}
        </nav>
        <div className="px-3 pb-4">
          {isAuthed && (
            <button onClick={logout} className="btn-ghost w-full justify-start">
              <LogOut size={16} />
              <span>Выйти</span>
            </button>
          )}
          {!authRequired && (
            <div className="text-xs text-slate-500 px-3 mt-2">
              Открытый режим (без токена)
            </div>
          )}
          {isAuthed && role === "operator" ? (
            <div className="text-xs text-slate-500 px-3 mt-2">Роль: оператор</div>
          ) : null}
        </div>
      </aside>
      <main className="flex-1 min-w-0">
        <header className="sticky top-0 z-10 flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-950/80 backdrop-blur">
          <div className="text-sm text-slate-400">
            Reels Publisher · админ-консоль
            {badges.failed > 0 ? (
              <span className="ml-2 text-rose-300">ошибки 24ч: {badges.failed}</span>
            ) : null}
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="btn-ghost text-xs py-1 px-2"
              onClick={() => setPaletteOpen(true)}
              title="Ctrl+K"
            >
              Перейти
            </button>
            <AgentToggle compact />
          </div>
        </header>
        <div className={clsx("p-6", dockHidden ? "pb-16" : "pb-40")}>
          <Outlet />
        </div>
      </main>
      <Assistant onHiddenChange={setDockHidden} />
      {paletteOpen ? <CommandPalette onClose={() => setPaletteOpen(false)} /> : null}
      <Modal open={helpOpen} onClose={() => setHelpOpen(false)} title="Клавиши">
        <ul className="space-y-2 text-sm text-slate-300">
          <li><kbd className="font-mono text-xs">Ctrl</kbd>+<kbd className="font-mono text-xs">K</kbd> — палитра</li>
          <li><kbd className="font-mono text-xs">/</kbd> — поиск на странице</li>
          <li><kbd className="font-mono text-xs">C</kbd> — чат агента</li>
          <li><kbd className="font-mono text-xs">J</kbd> / <kbd className="font-mono text-xs">K</kbd> — строка в очереди и библиотеке</li>
          <li><kbd className="font-mono text-xs">Enter</kbd> — открыть выделенное</li>
          <li><kbd className="font-mono text-xs">?</kbd> — эта шпаргалка</li>
        </ul>
      </Modal>
    </div>
  );
}

function NavBadge({ count }: { count: number }) {
  return (
    <span className="min-w-[1.25rem] rounded-full bg-rose-500/90 px-1.5 py-0.5 text-center text-[10px] font-semibold text-white">
      {count > 99 ? "99+" : count}
    </span>
  );
}
