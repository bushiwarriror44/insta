import clsx from "clsx";
import { Inbox } from "lucide-react";
import type { ReactNode } from "react";

type EmptyStateProps = {
  children: ReactNode;
  /** Short heading above the message */
  title?: string;
  /** Tighter layout for table rows and dense panels */
  compact?: boolean;
  /** Single primary action (button, link, or router Link) */
  action?: ReactNode;
};

export function EmptyState({ children, title, compact, action }: EmptyStateProps) {
  return (
    <div
      className={clsx(
        "flex flex-col items-center justify-center gap-2 text-slate-500 transition-opacity duration-200",
        compact ? "py-4 text-xs" : "py-8 text-sm"
      )}
    >
      <Inbox
        className={clsx("shrink-0 text-slate-600", compact ? "h-6 w-6" : "h-8 w-8")}
        aria-hidden
      />
      {title ? (
        <p className={clsx("font-medium text-slate-400", compact ? "text-xs" : "text-sm")}>
          {title}
        </p>
      ) : null}
      <div className="max-w-md text-center">{children}</div>
      {action ? <div className="mt-1 flex flex-wrap items-center justify-center gap-2">{action}</div> : null}
    </div>
  );
}
