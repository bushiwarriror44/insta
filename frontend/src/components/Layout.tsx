import {
  Activity as ActivityIcon,
  LayoutDashboard,
  Library,
  LogOut,
  Users,
} from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";
import clsx from "clsx";

import { useAuth } from "../context/AuthContext";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/accounts", label: "Accounts", icon: Users },
  { to: "/publishing", label: "Library", icon: Library },
  { to: "/activity", label: "Activity", icon: ActivityIcon },
];

export function Layout() {
  const { state, logout, authRequired } = useAuth();
  const isAuthed = state.state === "authed";

  return (
    <div className="min-h-screen flex bg-slate-950 text-slate-100">
      <aside className="w-60 shrink-0 border-r border-slate-800 bg-slate-900/40 flex flex-col">
        <div className="px-5 py-5 border-b border-slate-800">
          <div className="text-lg font-semibold tracking-tight">Reels Admin</div>
          <div className="text-xs text-slate-500 mt-0.5">Instagram automation</div>
        </div>
        <nav className="flex-1 px-3 py-4 space-y-1">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
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
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="px-3 pb-4">
          {isAuthed && (
            <button onClick={logout} className="btn-ghost w-full justify-start">
              <LogOut size={16} />
              <span>Logout</span>
            </button>
          )}
          {!authRequired && (
            <div className="text-xs text-slate-500 px-3 mt-2">
              Open mode (no token)
            </div>
          )}
        </div>
      </aside>
      <main className="flex-1 min-w-0">
        <header className="sticky top-0 z-10 flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-950/80 backdrop-blur">
          <div className="text-sm text-slate-400">
            Reels Publisher · admin console
          </div>
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
            <span className="text-xs text-slate-400">live</span>
          </div>
        </header>
        <div className="p-6">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
