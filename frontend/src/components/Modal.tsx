import { X } from "lucide-react";
import { useEffect, useId, useRef } from "react";
import type { ReactNode } from "react";

import { useFocusTrap } from "../hooks/useFocusTrap";

interface Props {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  footer?: ReactNode;
  widthClass?: string;
  /** When false, backdrop click does nothing (default true). */
  closeOnBackdrop?: boolean;
  /** When false, Escape does not close (default true). */
  closeOnEscape?: boolean;
  /** Return false to block close (e.g. confirm). */
  onBeforeClose?: () => boolean;
  trapFocus?: boolean;
  role?: "dialog";
}

export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  widthClass = "max-w-lg",
  closeOnBackdrop = true,
  closeOnEscape = true,
  onBeforeClose,
  trapFocus = false,
  role = "dialog",
}: Props) {
  const panelRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useFocusTrap(panelRef, open && trapFocus);

  const requestClose = () => {
    if (onBeforeClose && onBeforeClose() === false) return;
    onClose();
  };

  useEffect(() => {
    if (!open || !closeOnEscape) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") requestClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, closeOnEscape]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
      onMouseDown={closeOnBackdrop ? requestClose : undefined}
      aria-hidden={false}
    >
      <div
        ref={panelRef}
        role={role}
        aria-modal="true"
        aria-labelledby={titleId}
        className={`card w-full ${widthClass} max-h-[90vh] overflow-y-auto`}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between gap-2 px-5 py-4 border-b border-slate-800">
          <h3 id={titleId} className="text-base font-semibold">
            {title}
          </h3>
          <button
            type="button"
            onClick={requestClose}
            className="text-slate-400 hover:text-white"
            aria-label="Закрыть"
          >
            <X size={18} />
          </button>
        </header>
        <div className="p-5">{children}</div>
        {footer && (
          <footer className="px-5 py-3 border-t border-slate-800 flex items-center justify-end gap-2">
            {footer}
          </footer>
        )}
      </div>
    </div>
  );
}
