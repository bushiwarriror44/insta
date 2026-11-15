import { CONNECTIONS_INTRO, CONNECTIONS_SECTIONS } from "../pages/connections";
import type { DocSpan } from "../pages/docText";
import { LlmGatewayPanel } from "./LlmGatewayPanel";

function DocParagraphs({ paragraphs }: { paragraphs: DocSpan[] | DocSpan[][] }) {
  const blocks = Array.isArray(paragraphs[0]) ? (paragraphs as DocSpan[][]) : [paragraphs as DocSpan[]];
  return (
    <div className="space-y-2 text-sm leading-relaxed text-slate-400">
      {blocks.map((parts, index) => (
        <p key={index}>
          {parts.map((part, partIndex) =>
            typeof part === "string" ? (
              <span key={partIndex}>{part}</span>
            ) : (
              <a
                key={partIndex}
                href={part.href}
                className="text-sky-300 underline decoration-sky-300/40 underline-offset-2"
              >
                {part.text}
              </a>
            ),
          )}
        </p>
      ))}
    </div>
  );
}

export function AdministrationConnections() {
  return (
    <div className="space-y-4" data-testid="admin-connections-panel">
      <section className="card space-y-4 p-5">
        <h2 className="text-lg font-semibold text-slate-100">Подключения</h2>
        <DocParagraphs paragraphs={CONNECTIONS_INTRO} />
        {CONNECTIONS_SECTIONS.map((section) => (
          <details key={section.id} open className="rounded-lg border border-slate-800 bg-slate-950/50 px-3 py-2">
            <summary className="cursor-pointer text-sm font-medium text-slate-200">{section.title}</summary>
            <DocParagraphs paragraphs={section.body} />
          </details>
        ))}
      </section>
      <section className="card space-y-3 p-5" aria-labelledby="connections-creds-heading">
        <h2 id="connections-creds-heading" className="text-lg font-semibold text-slate-100">
          Данные и управление
        </h2>
        <p className="text-sm text-slate-400">
          Ключ шлюза, включение эндпоинтов /mcp и /llm/v1 и журнал последних обращений. Токен входа в
          панель сюда не подставляется.
        </p>
        <LlmGatewayPanel layout="admin" />
      </section>
    </div>
  );
}