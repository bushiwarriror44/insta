import clsx from "clsx";
import {
  AlertTriangle,
  Ban,
  Check,
  CheckCircle2,
  CircleHelp,
  Clock,
  Loader2,
  Pause,
  Shield,
  ShieldAlert,
  Thermometer,
  XCircle,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

const STYLES: Record<string, string> = {
  active: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  paused: "bg-slate-500/15 text-slate-300 ring-slate-500/30",
  challenge: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  blocked: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
  cooldown: "bg-orange-500/15 text-orange-300 ring-orange-500/30",
  awaiting_review: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  queued: "bg-slate-500/15 text-slate-300 ring-slate-500/30",
  running: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  done: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  failed: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  dead: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
  errors: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
  cancelled: "bg-slate-500/15 text-slate-400 ring-slate-500/30",
  info: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  warn: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  error: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
  critical: "bg-rose-600/20 text-rose-200 ring-rose-500/40",
  ok: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  bad: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
};

const LABELS: Record<string, string> = {
  active: "Активен",
  paused: "Пауза",
  challenge: "Челлендж",
  blocked: "Заблокирован",
  cooldown: "Пауза IG",
  awaiting_review: "На проверке",
  queued: "В очереди",
  running: "В работе",
  done: "Готово",
  failed: "Сбой",
  dead: "Мёртвая",
  errors: "Ошибки",
  cancelled: "Отменена",
  info: "Инфо",
  warn: "Предупр.",
  error: "Ошибка",
  critical: "Критично",
  ok: "ОК",
  bad: "Плохо",
};

const ICONS: Record<string, LucideIcon> = {
  active: CheckCircle2,
  paused: Pause,
  challenge: Shield,
  blocked: Ban,
  cooldown: Thermometer,
  awaiting_review: Shield,
  queued: Clock,
  running: Loader2,
  done: Check,
  failed: AlertTriangle,
  dead: AlertTriangle,
  errors: AlertTriangle,
  cancelled: Ban,
  info: CircleHelp,
  warn: AlertTriangle,
  error: XCircle,
  critical: ShieldAlert,
  ok: CheckCircle2,
  bad: XCircle,
};

export function StatusBadge({ value }: { value: string }) {
  const key = value.toLowerCase();
  const Icon = ICONS[key];
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-full ring-1",
        STYLES[key] ?? "bg-slate-700/40 text-slate-300 ring-slate-600/30"
      )}
    >
      {Icon ? (
        <Icon
          className={clsx("h-3 w-3 shrink-0", key === "running" && "animate-spin")}
          aria-hidden
        />
      ) : null}
      {LABELS[key] ?? value}
    </span>
  );
}
