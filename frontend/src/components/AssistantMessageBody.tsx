import { Check, Copy } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";

import { copyTextToClipboard } from "./DiagnosticLogPanel";

const URL_RE = /https?:\/\/[^\s<]+[^\s<.,;:!?)]/gi;
const FENCE_RE = /```([\s\S]*?)```/g;

type Props = {
  content: string;
  onCopyToast?: (ok: boolean) => void;
};

function linkifySegment(text: string, keyBase: string) {
  const parts: Array<{ kind: "text" | "link"; value: string }> = [];
  let last = 0;
  const re = new RegExp(URL_RE.source, "gi");
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push({ kind: "text", value: text.slice(last, m.index) });
    parts.push({ kind: "link", value: m[0] });
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push({ kind: "text", value: text.slice(last) });
  if (!parts.length) parts.push({ kind: "text", value: text });
  return parts.map((part, i) =>
    part.kind === "link" ? (
      <a
        key={`${keyBase}-l-${i}`}
        href={part.value}
        target="_blank"
        rel="noopener noreferrer"
        className="text-sky-400 underline underline-offset-2 hover:text-sky-300"
      >
        {part.value}
      </a>
    ) : (
      <InlineCode key={`${keyBase}-t-${i}`} text={part.value} />
    )
  );
}

function InlineCode({ text }: { text: string }) {
  const bits: ReactNode[] = [];
  const re = /`([^`]+)`/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) bits.push(text.slice(last, m.index));
    bits.push(
      <code key={`ic-${i++}`} className="rounded bg-slate-800 px-1 py-0.5 font-mono text-[0.9em] text-slate-200">
        {m[1]}
      </code>
    );
    last = m.index + m[0].length;
  }
  if (last < text.length) bits.push(text.slice(last));
  return <>{bits}</>;
}

type Block =
  | { type: "paragraph"; text: string }
  | { type: "code"; text: string };

function parseBlocks(content: string): Block[] {
  const blocks: Block[] = [];
  let cursor = 0;
  const re = new RegExp(FENCE_RE.source, "g");
  let m: RegExpExecArray | null;
  while ((m = re.exec(content)) !== null) {
    if (m.index > cursor) {
      const chunk = content.slice(cursor, m.index);
      chunk
        .split(/\n\n+/)
        .map((p) => p.trim())
        .filter(Boolean)
        .forEach((p) => blocks.push({ type: "paragraph", text: p }));
    }
    let code = m[1].trim();
    const lang = code.match(/^([a-z0-9+#-]+)\s*\n/i);
    if (lang) code = code.slice(lang[0].length);
    blocks.push({ type: "code", text: code });
    cursor = m.index + m[0].length;
  }
  const tail = content.slice(cursor);
  tail
    .split(/\n\n+/)
    .map((p) => p.trim())
    .filter(Boolean)
    .forEach((p) => blocks.push({ type: "paragraph", text: p }));
  if (!blocks.length && content.trim()) {
    blocks.push({ type: "paragraph", text: content.trim() });
  }
  return blocks;
}

export function AssistantMessageBody({ content, onCopyToast }: Props) {
  const blocks = useMemo(() => parseBlocks(content), [content]);
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    const ok = await copyTextToClipboard(content);
    onCopyToast?.(ok);
    if (ok) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    }
  };

  return (
    <div className="group relative space-y-2 text-sm text-slate-100">
      <button
        type="button"
        className="absolute -top-1 right-0 rounded-md border border-transparent p-1 text-slate-500 opacity-0 transition hover:border-slate-700 hover:bg-slate-800 hover:text-slate-200 focus:opacity-100 group-hover:opacity-100 group-focus-within:opacity-100"
        aria-label="Скопировать ответ"
        title="Скопировать ответ"
        onClick={() => void copy()}
      >
        {copied ? <Check size={14} className="text-emerald-400" /> : <Copy size={14} />}
      </button>
      {blocks.map((block, i) =>
        block.type === "code" ? (
          <pre
            key={`c-${i}`}
            className="overflow-x-auto rounded-lg border border-slate-800 bg-slate-950/80 p-2 font-mono text-xs text-slate-200"
          >
            {block.text}
          </pre>
        ) : (
          <p key={`p-${i}`} className="whitespace-pre-wrap">
            {linkifySegment(block.text, `p-${i}`)}
          </p>
        )
      )}
    </div>
  );
}
