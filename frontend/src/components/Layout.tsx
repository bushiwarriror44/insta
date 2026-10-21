import {
  BookOpen,
  CalendarDays,
  Clapperboard,
  Sparkles,
  Activity as ActivityIcon,
  KeyRound,
  LayoutDashboard,
  Library,
  LogOut,
  Menu,
  Settings as SettingsIcon,
  Users,
  Wrench,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, NavLink, Outlet } from "react-router-dom";
import clsx from "clsx";

import { api } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { useGpuPresence } from "../hooks/useGpuPresence";
import { useHotkeys } from "../hooks/useHotkeys";
import { usePollWhenVisible } from "../hooks/usePollWhenVisible";
import { focusPageSearch, REFRESH_NAV_BADGES, showAssistant } from "../lib/uiEvents";
import { AgentToggle } from "./AgentToggle";
import { ConnectionMenu } from "./ConnectionMenu";
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

type Badges = {
  review: number;
  failed: number;
  questions: number;
  questionsAccountId: number | null;
};

export function Layout() {
  const { state, logout, authRequired, role } = useAuth();
  const isAuthed = state.state === "authed";
  const isOwner = role === "owner";
  const showAdmin = isOwner || !authRequired;
  const [dockHidden, setDockHidden] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [badges, setBadges] = useState<Badges>({
    review: 0,
    failed: 0,
    questions: 0,
    questionsAccountId: null,
  });

  const closeNav = useCallback(() => setNavOpen(false), []);

  const loadBadges = useCallback(async () => {
    try {
      const summary = await api.dashboard();
      setBadges({
        review: summary.jobs_awaiting_review ?? 0,
        failed: summary.jobs_failed_24h ?? 0,
        questions: summary.open_questions ?? 0,
        questionsAccountId: summary.questions_account_id ?? null,
      });
    } catch {
      /* nav badges stay on last known */
    }
  }, []);

  useGpuPresence(isAuthed || !authRequired);
  usePollWhenVisible(loadBadges, 15000);

  useEffect(() => {
    window.addEventListener(REFRESH_NAV_BADGES, loadBadges);
    return () => window.removeEventListener(REFRESH_NAV_BADGES, loadBadges);
  }, [loadBadges]);

  useEffect(() => {
    if (!navOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setNavOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navOpen]);

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

  useHotkeys(hotkeys, !paletteOpen && !helpOpen && !navOpen);

  const navClass = ({ isActive }: { isActive: boolean }) =>
    clsx(
      "flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors",
      isActive
        ? "bg-brand-500/15 text-brand-200"
        : "text-slate-300 hover:bg-slate-800/60 hover:text-white"
    );

  return (
    <div className="flex min-h-screen bg-slate-950 text-slate-100">
      {navOpen ? (
        <button
          type="button"
          className="fixed inset-0 z-30 bg-slate-950/70 md:hidden"
          aria-label="Закрыть меню"
          onClick={closeNav}
        />
      ) : null}

      <aside
        className={clsx(
          "fixed inset-y-0 left-0 z-40 flex w-60 max-w-[85vw] flex-col border-r border-slate-800 bg-slate-950 transition-transform duration-200 md:static md:z-auto md:h-screen md:max-w-none md:shrink-0 md:translate-x-0 md:bg-slate-900/40",
          navOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"
        )}
        aria-label="Навигация"
      >
        <div className="flex items-center justify-between border-b border-slate-800 px-3 py-3 md:hidden">
          <span className="px-2 text-sm font-medium text-slate-200">Меню</span>
          <button type="button" className="btn-ghost px-2 py-1" aria-label="Закрыть" onClick={closeNav}>
            <X size={16} />
          </button>
        </div>
        <div className="hidden border-b border-slate-800 px-5 py-5 md:block">
          <div className="text-lg font-semibold tracking-tight">Reels Admin</div>
          <div className="mt-0.5 text-xs text-slate-500">Instagram · YouTube · TikTok</div>
        </div>
        <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-4" aria-label="Основное меню">
          {NAV.map(({ to, label, icon: Icon, end, testId, badge }) => {
            const href =
              badge === "review" && badges.review > 0
                ? "/activity?status=awaiting_review"
                : badge === "questions" && badges.questionsAccountId
                  ? `/agent?account=${badges.questionsAccountId}`
                  : to;
            return (
              <NavLink
                key={to}
                to={href}
                end={end}
                data-testid={testId}
                className={navClass}
                onClick={closeNav}
              >
                <Icon size={18} />
                <span className="flex-1">{label}</span>
                {badge === "review" && badges.review > 0 ? <NavBadge count={badges.review} /> : null}
                {badge === "questions" && badges.questions > 0 ? (
                  <NavBadge count={badges.questions} />
                ) : null}
              </NavLink>
            );
          })}
          {showAdmin ? (
            <NavLink
              to="/administration"
              data-testid="nav-administration"
              className={navClass}
              onClick={closeNav}
            >
              <BookOpen size={18} />
              <span>Администрирование</span>
            </NavLink>
          ) : null}
          {isOwner ? (
            <>
              <NavLink to="/operators" data-testid="nav-operators" className={navClass} onClick={closeNav}>
                <KeyRound size={18} />
                <span>Доступы</span>
              </NavLink>
              <NavLink to="/settings" data-testid="nav-settings" className={navClass} onClick={closeNav}>
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
            <div className="mt-2 px-3 text-xs text-slate-500">Открытый режим (без токена)</div>
          )}
          {isAuthed && role === "operator" ? (
            <div className="mt-2 px-3 text-xs text-slate-500">Роль: оператор</div>
          ) : null}
        </div>
      </aside>

      <main className="min-w-0 flex-1">
        <header className="sticky top-0 z-10 flex items-center justify-between gap-2 border-b border-slate-800 bg-slate-950/80 px-3 py-3 backdrop-blur sm:px-6 sm:py-4">
          <div className="flex min-w-0 items-center gap-2">
            <button
              type="button"
              className="btn-ghost shrink-0 px-2 py-1 md:hidden"
              aria-label="Меню"
              aria-expanded={navOpen}
              onClick={() => setNavOpen(true)}
            >
              <Menu size={18} />
            </button>
            <div className="truncate text-sm text-slate-400">
              <span className="hidden sm:inline">Reels Publisher · админ-консоль</span>
              <span className="sm:hidden">Reels Admin</span>
              {badges.failed > 0 ? (
                <Link to="/activity?status=errors" className="ml-2 text-rose-300 hover:text-rose-200">
                  ошибки 24ч: {badges.failed}
                </Link>
              ) : null}
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <button
              type="button"
              className="btn-ghost px-2 py-1 text-xs"
              onClick={() => setPaletteOpen(true)}
              title="Ctrl+K"
            >
              Перейти
            </button>
            {showAdmin ? <ConnectionMenu /> : null}
            <AgentToggle compact />
          </div>
        </header>
        <div className={clsx("p-3 sm:p-6", dockHidden ? "pb-16" : "pb-40")}>
          <Outlet />
        </div>
      </main>
      <Assistant onHiddenChange={setDockHidden} />
      {paletteOpen ? <CommandPalette onClose={() => setPaletteOpen(false)} /> : null}
      <Modal open={helpOpen} onClose={() => setHelpOpen(false)} title="Клавиши">
        <ul className="space-y-2 text-sm text-slate-300">
          <li>
            <kbd className="font-mono text-xs">Ctrl</kbd>+<kbd className="font-mono text-xs">K</kbd> — палитра
          </li>
          <li>
            <kbd className="font-mono text-xs">/</kbd> — поиск на странице
          </li>
          <li>
            <kbd className="font-mono text-xs">C</kbd> — чат агента
          </li>
          <li>
            <kbd className="font-mono text-xs">J</kbd> / <kbd className="font-mono text-xs">K</kbd> — строка в очереди и
            библиотеке
          </li>
          <li>
            <kbd className="font-mono text-xs">Enter</kbd> — открыть выделенное
          </li>
          <li>
            <kbd className="font-mono text-xs">?</kbd> — эта шпаргалка
          </li>
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
