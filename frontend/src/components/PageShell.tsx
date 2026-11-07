import { RefreshCw } from "lucide-react";
import clsx from "clsx";
import type { ReactNode } from "react";

type Props = {
  children: ReactNode;
  className?: string;
  error?: string | null;
  onRetry?: () => void;
  retryLabel?: string;
};

export function PageShell({
  children,
  className,
  error,
  onRetry,
  retryLabel = "Повторить",
}: Props) {
  return (
    <div className={clsx("space-y-6", className)}>
      {error ? (
        <div
          className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-rose-900/40 bg-rose-950/20 px-4 py-3"
          role="alert"
        >
          <p className="text-sm text-rose-200 break-words">{error}</p>
          {onRetry ? (
            <button type="button" className="btn-ghost text-sm shrink-0" onClick={onRetry}>
              <RefreshCw size={14} />
              {retryLabel}
            </button>
          ) : null}
        </div>
      ) : null}
      {children}
    </div>
  );
}
