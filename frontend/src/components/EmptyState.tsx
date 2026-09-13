import { Inbox } from "lucide-react";
import type { ReactNode } from "react";

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-8 text-sm text-slate-500">
      <Inbox className="h-8 w-8 text-slate-600" aria-hidden />
      {children}
    </div>
  );
}
