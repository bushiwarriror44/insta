import clsx from "clsx";

import type { AssistantCardKind } from "../api/assistant";

const LABEL: Partial<Record<AssistantCardKind, string>> = {
  accounts: "Аккаунты",
  renders: "Рендеры",
  clips: "Библиотека",
};

const ROWS = 4;

function useReducedMotion(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

type Props = {
  kind?: AssistantCardKind | null;
};

export function AssistantCardsSkeleton({ kind }: Props) {
  const reduced = useReducedMotion();
  const title = kind ? LABEL[kind] : "Списки";

  return (
    <div
      className="mt-2 rounded-xl border border-slate-800 bg-slate-950/50 p-2.5"
      data-testid="assistant-cards-skeleton"
      role="status"
      aria-busy="true"
      aria-label={title ? `Загрузка: ${title}` : "Загрузка списков"}
    >
      <div className="mb-2 h-3 w-24 rounded bg-slate-800/90" />
      <ul className="space-y-2" aria-hidden>
        {Array.from({ length: ROWS }, (_, i) => (
          <li
            key={i}
            className={clsx(
              "flex items-center justify-between gap-2 py-2",
              !reduced && "animate-pulse"
            )}
          >
            <div className="min-w-0 flex-1 space-y-1.5">
              <div className="h-3 w-32 max-w-full rounded bg-slate-800/80" />
              <div className="h-2.5 w-48 max-w-full rounded bg-slate-800/60" />
            </div>
            <div className="h-8 w-16 shrink-0 rounded-lg bg-slate-800/70" />
          </li>
        ))}
      </ul>
    </div>
  );
}
