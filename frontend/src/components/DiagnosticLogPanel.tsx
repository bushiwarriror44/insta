import { useEffect, useRef } from "react";

import type { DiagnosticLogLine } from "../api/types";

const LEVEL_CLASS: Record<DiagnosticLogLine["level"], string> = {
  info: "text-slate-300",
  warn: "text-amber-300",
  error: "text-rose-300",
};

function formatTime(iso: string) {
  try {
    return new Date(iso).toLocaleTimeString();
  } catch {
    return iso;
  }
}

interface Props {
  lines: DiagnosticLogLine[];
  emptyLabel?: string;
  maxHeightClass?: string;
  autoScroll?: boolean;
}

export function DiagnosticLogPanel({
  lines,
  emptyLabel = "No log lines yet.",
  maxHeightClass = "max-h-56",
  autoScroll = true,
}: Props) {
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!autoScroll) return;
    bottomRef.current?.scrollIntoView?.({ behavior: "smooth" });
  }, [lines, autoScroll]);

  if (lines.length === 0) {
    return (
      <div className="rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-4 text-xs text-slate-500">
        {emptyLabel}
      </div>
    );
  }

  return (
    <div
      className={`rounded-lg border border-slate-800 bg-slate-950/60 overflow-y-auto font-mono text-xs ${maxHeightClass}`}
    >
      <ul className="divide-y divide-slate-800/80">
        {lines.map((line, idx) => (
          <li key={`${line.ts}-${idx}`} className="px-3 py-2 flex gap-2 items-start">
            <span className="text-slate-500 shrink-0 tabular-nums">{formatTime(line.ts)}</span>
            <span className="text-slate-500 shrink-0 w-14 uppercase">{line.step}</span>
            <span className={`min-w-0 break-words ${LEVEL_CLASS[line.level]}`}>{line.message}</span>
          </li>
        ))}
      </ul>
      <div ref={bottomRef} />
    </div>
  );
}
