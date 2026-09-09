import clsx from "clsx";
import type { LucideIcon } from "lucide-react";
import { Link } from "react-router-dom";

interface Props {
  label: string;
  value: number | string;
  icon: LucideIcon;
  hint?: string;
  tone?: "default" | "success" | "warn" | "danger" | "info";
  to?: string;
}

const TONE_BG: Record<NonNullable<Props["tone"]>, string> = {
  default: "bg-slate-800/60 text-slate-300",
  success: "bg-emerald-900/40 text-emerald-300",
  warn: "bg-amber-900/40 text-amber-300",
  danger: "bg-rose-900/40 text-rose-300",
  info: "bg-sky-900/40 text-sky-300",
};

export function StatCard({ label, value, icon: Icon, hint, tone = "default", to }: Props) {
  const inner = (
    <>
      <div className={clsx("rounded-xl p-3", TONE_BG[tone])}>
        <Icon size={22} />
      </div>
      <div className="min-w-0">
        <div className="text-sm text-slate-400">{label}</div>
        <div className="text-2xl font-semibold tabular-nums mt-0.5">{value}</div>
        {hint && <div className="text-xs text-slate-500 mt-1">{hint}</div>}
      </div>
    </>
  );
  const className = clsx(
    "card p-5 flex items-start gap-4",
    to && "hover:border-brand-500/40 hover:bg-slate-900/40 transition-colors"
  );
  if (to) {
    return (
      <Link to={to} className={className} aria-label={label}>
        {inner}
      </Link>
    );
  }
  return <div className={className}>{inner}</div>;
}
