import clsx from "clsx";

const STYLES: Record<string, string> = {
  active: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  paused: "bg-slate-500/15 text-slate-300 ring-slate-500/30",
  challenge: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  blocked: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
  cooldown: "bg-orange-500/15 text-orange-300 ring-orange-500/30",
  queued: "bg-slate-500/15 text-slate-300 ring-slate-500/30",
  running: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  done: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  failed: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  dead: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
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
  challenge: "Проверка",
  blocked: "Заблокирован",
  cooldown: "Пауза IG",
  queued: "В очереди",
  running: "В работе",
  done: "Готово",
  failed: "Сбой",
  dead: "Мёртвая",
  cancelled: "Отменена",
  info: "Инфо",
  warn: "Предупр.",
  error: "Ошибка",
  critical: "Критично",
  ok: "ОК",
  bad: "Плохо",
};

export function StatusBadge({ value }: { value: string }) {
  const key = value.toLowerCase();
  return (
    <span
      className={clsx(
        "inline-flex items-center px-2 py-0.5 text-xs font-medium rounded-full ring-1",
        STYLES[key] ?? "bg-slate-700/40 text-slate-300 ring-slate-600/30"
      )}
    >
      {LABELS[key] ?? value}
    </span>
  );
}
