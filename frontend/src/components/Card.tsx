import clsx from "clsx";
import type { ReactNode } from "react";

interface Props {
  id?: string;
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
  children: ReactNode;
}

export function Card({ id, title, description, actions, className, children }: Props) {
  return (
    <section id={id} className={clsx("card overflow-hidden", className)}>
      {(title || actions) && (
        <header className="flex items-start justify-between gap-4 px-5 py-4 border-b border-slate-800">
          <div>
            {title && <h2 className="text-lg font-semibold text-slate-100">{title}</h2>}
            {description && (
              <p className="text-sm text-slate-400 mt-0.5">{description}</p>
            )}
          </div>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className="flex flex-col gap-4 p-5">{children}</div>
    </section>
  );
}
