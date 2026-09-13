import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

export function PageHeader({
  icon: Icon,
  title,
  description,
}: {
  icon: LucideIcon;
  title: string;
  description?: ReactNode;
}) {
  return (
    <div>
      <h1 className="text-2xl font-semibold flex items-center gap-2">
        <Icon className="h-6 w-6 shrink-0 text-brand-400" aria-hidden />
        {title}
      </h1>
      {description ? <p className="text-sm text-slate-400 mt-1">{description}</p> : null}
    </div>
  );
}
