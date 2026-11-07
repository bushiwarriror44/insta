import clsx from "clsx";

function useReducedMotion(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

type Props = {
  rows?: number;
  columns?: number;
  className?: string;
};

export function TableSkeleton({ rows = 6, columns = 5, className }: Props) {
  const reduced = useReducedMotion();
  const pulse = reduced ? "" : "animate-pulse";

  return (
    <div className={clsx("table-scroll", className)} role="status" aria-label="Загрузка таблицы">
      <table className="table-base" data-testid="table-skeleton">
        <thead>
          <tr>
            {Array.from({ length: columns }, (_, i) => (
              <th key={`h-${i}`}>
                <span className={clsx("block h-3 w-16 max-w-full rounded bg-slate-800", pulse)} />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: rows }, (_, r) => (
            <tr key={`r-${r}`}>
              {Array.from({ length: columns }, (_, c) => (
                <td key={`c-${c}`}>
                  <span
                    className={clsx("block h-3 rounded bg-slate-800/90", pulse)}
                    style={{ width: `${52 + ((r + c) % 4) * 11}%` }}
                  />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
