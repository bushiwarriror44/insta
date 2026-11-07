import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";

import { ConfirmDialog } from "../components/ConfirmDialog";

export type ConfirmOptions = {
  title: string;
  body: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
};

type ConfirmCtx = {
  confirm: (options: ConfirmOptions) => Promise<boolean>;
};

const Ctx = createContext<ConfirmCtx | null>(null);

type ActiveConfirm = ConfirmOptions & { open: true };

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [active, setActive] = useState<ActiveConfirm | null>(null);
  const resolveRef = useRef<((value: boolean) => void) | null>(null);

  const confirm = useCallback((options: ConfirmOptions) => {
    return new Promise<boolean>((resolve) => {
      resolveRef.current = resolve;
      setActive({ ...options, open: true });
    });
  }, []);

  const finish = useCallback((ok: boolean) => {
    resolveRef.current?.(ok);
    resolveRef.current = null;
    setActive(null);
  }, []);

  const value = useMemo(() => ({ confirm }), [confirm]);

  return (
    <Ctx.Provider value={value}>
      {children}
      {active ? (
        <ConfirmDialog
          open
          title={active.title}
          body={active.body}
          confirmLabel={active.confirmLabel}
          cancelLabel={active.cancelLabel}
          danger={active.danger}
          onConfirm={() => finish(true)}
          onCancel={() => finish(false)}
        />
      ) : null}
    </Ctx.Provider>
  );
}

export function useConfirm(): ConfirmCtx["confirm"] {
  const ctx = useContext(Ctx);
  if (!ctx) {
    throw new Error("useConfirm requires ConfirmProvider");
  }
  return ctx.confirm;
}
