import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { CheckCircle2, AlertTriangle, X, Info } from "lucide-react";
import clsx from "clsx";
import { Link } from "react-router-dom";

type ToastKind = "success" | "error" | "info";

export type ToastAction = {
  label: string;
  href?: string;
  onClick?: () => void;
};

interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
  action?: ToastAction;
}

interface ToastCtx {
  push: (message: string, kind?: ToastKind, action?: ToastAction) => void;
}

const Ctx = createContext<ToastCtx | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);

  const remove = useCallback((id: number) => {
    setItems((arr) => arr.filter((t) => t.id !== id));
  }, []);

  const push = useCallback(
    (message: string, kind: ToastKind = "info", action?: ToastAction) => {
      const id = Date.now() + Math.random();
      setItems((arr) => [...arr, { id, kind, message, action }]);
      window.setTimeout(() => remove(id), action ? 8000 : 4500);
    },
    [remove]
  );

  const value = useMemo(() => ({ push }), [push]);

  return (
    <Ctx.Provider value={value}>
      {children}
      <div className="fixed top-4 right-4 z-50 flex flex-col gap-2 max-w-sm">
        {items.map((t) => (
          <div
            key={t.id}
            className={clsx(
              "flex items-start gap-3 rounded-lg border px-3 py-2 shadow-lg backdrop-blur",
              t.kind === "success" && "bg-emerald-900/70 border-emerald-700/60 text-emerald-100",
              t.kind === "error" && "bg-rose-900/70 border-rose-700/60 text-rose-100",
              t.kind === "info" && "bg-slate-800/80 border-slate-700/60 text-slate-100"
            )}
          >
            <div className="pt-0.5">
              {t.kind === "success" && <CheckCircle2 size={18} />}
              {t.kind === "error" && <AlertTriangle size={18} />}
              {t.kind === "info" && <Info size={18} />}
            </div>
            <div className="text-sm flex-1 min-w-0">
              <div className="break-words">{t.message}</div>
              {t.action ? (
                t.action.href ? (
                  <Link
                    to={t.action.href}
                    className="mt-1 inline-block text-xs font-medium underline decoration-dotted underline-offset-2 hover:text-white"
                    onClick={() => {
                      t.action?.onClick?.();
                      remove(t.id);
                    }}
                  >
                    {t.action.label}
                  </Link>
                ) : (
                  <button
                    type="button"
                    className="mt-1 text-xs font-medium underline decoration-dotted underline-offset-2 hover:text-white"
                    onClick={() => {
                      t.action?.onClick?.();
                      remove(t.id);
                    }}
                  >
                    {t.action.label}
                  </button>
                )
              ) : null}
            </div>
            <button
              onClick={() => remove(t.id)}
              className="text-slate-300 hover:text-white"
              aria-label="Закрыть"
            >
              <X size={16} />
            </button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

export function useToast() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useToast outside ToastProvider");
  return ctx;
}
