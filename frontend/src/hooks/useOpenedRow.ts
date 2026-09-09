import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";

export function useOpenedRow<T extends { id: number }>(
  name: string,
  rows: T[] | null | undefined,
  show: (row: T) => void
) {
  const [params, setParams] = useSearchParams();
  const asked = params.get(name);

  useEffect(() => {
    if (!asked || !rows) return;
    const wanted = rows.find((row) => row.id === Number(asked));
    if (!wanted) return;
    show(wanted);
    const next = new URLSearchParams(params);
    next.delete(name);
    setParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [asked, rows]);
}
