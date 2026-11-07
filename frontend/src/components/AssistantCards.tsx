import { ExternalLink, Globe } from "lucide-react";
import { useCallback, useRef, useState, type KeyboardEvent } from "react";

import type { AssistantCardBlock } from "../api/assistant";
import { CountryFlag } from "./CountryFlag";
import { EmptyState } from "./EmptyState";
import { normalizePlatform, PlatformIcon } from "./PlatformIcon";
import { StatusBadge } from "./StatusBadge";

export type ChatBrowserTarget = {
  username: string;
  platform?: string;
  proxy_label?: string | null;
  login_surface?: string | null;
};

const INITIAL_VISIBLE = 8;

const SECTION_TITLE: Record<AssistantCardBlock["kind"], string> = {
  accounts: "Аккаунты",
  renders: "Рендеры в очереди",
  clips: "Библиотека",
};

const SECTION_LINK: Partial<Record<AssistantCardBlock["kind"], string>> = {
  renders: "/renders",
  clips: "/publishing",
  accounts: "/accounts",
};

const EMPTY_COPY: Record<AssistantCardBlock["kind"], { title: string; body: string; cta: string }> = {
  accounts: {
    title: "Нет аккаунтов",
    body: "Создайте аккаунт на странице или попросите агента.",
    cta: "Добавить аккаунт",
  },
  renders: {
    title: "Очередь пуста",
    body: "Новые рендеры появятся после generate или create_render.",
    cta: "Открыть рендеры",
  },
  clips: {
    title: "Библиотека пуста",
    body: "Загрузите видео или изображения в библиотеку.",
    cta: "Открыть библиотеку",
  },
};

type Props = {
  blocks: AssistantCardBlock[];
  onNavigate: (path: string) => void;
  onOpenAccount: (accountId: number) => void;
  onOpenBrowser: (target: ChatBrowserTarget, trigger?: HTMLElement | null) => void;
};


function str(item: Record<string, unknown>, key: string): string {
  const v = item[key];
  if (v == null) return "";
  return String(v);
}

function num(item: Record<string, unknown>, key: string): number | null {
  const v = item[key];
  if (v == null || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function CardSection({
  block,
  expanded,
  onToggleExpand,
  onNavigate,
  onOpenAccount,
  onOpenBrowser,
}: {
  block: AssistantCardBlock;
  expanded: boolean;
  onToggleExpand: () => void;
  onNavigate: (path: string) => void;
  onOpenAccount: (accountId: number) => void;
  onOpenBrowser: (target: ChatBrowserTarget, trigger?: HTMLElement | null) => void;
}) {
  const title = SECTION_TITLE[block.kind];
  const sectionHref = SECTION_LINK[block.kind];
  const empty = EMPTY_COPY[block.kind];
  const visibleItems = expanded ? block.items : block.items.slice(0, INITIAL_VISIBLE);
  const hiddenCount = block.items.length - INITIAL_VISIBLE;
  const rowRefs = useRef<(HTMLLIElement | null)[]>([]);

  const focusRow = useCallback((index: number) => {
    rowRefs.current[index]?.focus();
  }, []);

  const onAccountRowKey = (index: number, accountId: number | null, e: KeyboardEvent<HTMLLIElement>) => {
    if (e.key === "Enter" && accountId != null) {
      e.preventDefault();
      onOpenAccount(accountId);
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      focusRow(Math.min(index + 1, visibleItems.length - 1));
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      focusRow(Math.max(index - 1, 0));
    }
  };

  return (
    <section
      className="assistant-cards-in rounded-xl border border-slate-800 bg-slate-950/50 p-2.5"
      aria-label={title}
    >
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-400">{title}</h4>
        {sectionHref ? (
          <button
            type="button"
            className="btn-ghost min-h-9 text-[11px] py-1.5"
            onClick={() => onNavigate(sectionHref)}
          >
            <ExternalLink size={12} />
            Открыть страницу
          </button>
        ) : null}
      </div>
      {block.items.length === 0 ? (
        <EmptyState compact title={empty.title} action={
          sectionHref ? (
            <button type="button" className="btn-primary text-xs" onClick={() => onNavigate(sectionHref)}>
              {empty.cta}
            </button>
          ) : null
        }>
          {empty.body}
        </EmptyState>
      ) : (
        <>
          <ul className="divide-y divide-slate-800/80">
            {block.kind === "accounts"
              ? visibleItems.map((row, rowIndex) => {
                  const id = num(row, "id");
                  const username = str(row, "username");
                  const key = id ?? username;
                  const canBrowser = Boolean(str(row, "proxy_label"));
                  const platform = str(row, "platform") || "instagram";
                  const geo = str(row, "proxy_geo_country") || str(row, "proxy_country");
                  return (
                    <li
                      key={String(key)}
                      ref={(el) => {
                        rowRefs.current[rowIndex] = el;
                      }}
                      role="row"
                      tabIndex={rowIndex === 0 ? 0 : -1}
                      className="flex flex-wrap items-center justify-between gap-2 rounded-lg py-2 text-xs outline-none transition-colors hover:bg-slate-900/40 focus-visible:ring-2 focus-visible:ring-sky-500/40"
                      onKeyDown={(e) => onAccountRowKey(rowIndex, id, e)}
                    >
                      <div className="min-w-0 flex-1 space-y-0.5">
                        <div className="flex flex-wrap items-center gap-2">
                          <PlatformIcon platform={platform} size={14} />
                          <span className="font-medium text-slate-100">@{username}</span>
                          {str(row, "status") ? <StatusBadge value={str(row, "status")} /> : null}
                        </div>
                        <p className="flex flex-wrap items-center gap-1 text-slate-500 truncate pl-[22px]">
                          {normalizePlatform(platform)}
                          {geo ? (
                            <>
                              <span className="text-slate-600">·</span>
                              <CountryFlag code={geo} showCode />
                            </>
                          ) : null}
                          {str(row, "proxy_label") ? ` · ${str(row, "proxy_label")}` : " · без прокси"}
                        </p>
                      </div>
                      <div className="flex shrink-0 flex-wrap items-center gap-1">
                        {id != null ? (
                          <button
                            type="button"
                            className="btn-ghost min-h-9 text-[11px] py-2"
                            onClick={() => onOpenAccount(id)}
                          >
                            Карточка
                          </button>
                        ) : null}
                        {canBrowser ? (
                          <button
                            type="button"
                            className="btn-primary min-h-9 text-[11px] py-2"
                            title="Интерактивный браузер (VNC)"
                            onClick={(e) =>
                              onOpenBrowser(
                                {
                                  username,
                                  platform,
                                  proxy_label: str(row, "proxy_label") || null,
                                },
                                e.currentTarget
                              )
                            }
                          >
                            <Globe size={12} />
                            Браузер
                          </button>
                        ) : id != null ? (
                          <button
                            type="button"
                            className="btn-ghost min-h-9 text-[11px] py-2"
                            aria-describedby={`proxy-hint-${id}`}
                            onClick={() => onNavigate(`/accounts?id=${id}`)}
                          >
                            Назначить прокси
                          </button>
                        ) : (
                          <span id={id != null ? `proxy-hint-${id}` : undefined} className="px-1 text-[10px] text-slate-500">
                            Нужен прокси
                          </span>
                        )}
                      </div>
                    </li>
                  );
                })
              : null}
            {block.kind === "renders"
              ? visibleItems.map((row) => {
                  const id = num(row, "id");
                  const key = id ?? str(row, "prompt");
                  return (
                    <li
                      key={String(key)}
                      className="flex flex-wrap items-center justify-between gap-2 rounded-lg py-2 text-xs transition-colors hover:bg-slate-900/40"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-mono text-slate-300">{id != null ? `#${id}` : "—"}</span>
                          {str(row, "status") ? <StatusBadge value={str(row, "status")} /> : null}
                          {str(row, "backend") ? (
                            <span className="text-slate-500">{str(row, "backend")}</span>
                          ) : null}
                        </div>
                        <p className="mt-0.5 truncate text-slate-400" title={str(row, "prompt")}>
                          {str(row, "prompt") || "—"}
                        </p>
                      </div>
                      {id != null ? (
                        <button
                          type="button"
                          className="btn-ghost min-h-9 text-[11px] py-2"
                          onClick={() => onNavigate(`/renders?gen=${id}`)}
                        >
                          Открыть
                        </button>
                      ) : null}
                    </li>
                  );
                })
              : null}
            {block.kind === "clips"
              ? visibleItems.map((row) => {
                  const filename = str(row, "filename");
                  const key = filename || str(row, "id");
                  return (
                    <li
                      key={key}
                      className="flex flex-wrap items-center justify-between gap-2 rounded-lg py-2 text-xs transition-colors hover:bg-slate-900/40"
                    >
                      <div className="min-w-0 flex-1">
                        <p className="truncate font-mono text-slate-200" title={filename}>
                          {filename || str(row, "label") || "—"}
                        </p>
                        <p className="text-slate-500">
                          {str(row, "media_type") || "video"}
                          {row.seconds != null ? ` · ${row.seconds}s` : ""}
                        </p>
                      </div>
                      {filename ? (
                        <button
                          type="button"
                          className="btn-ghost min-h-9 text-[11px] py-2"
                          onClick={() =>
                            onNavigate(
                              `/publishing?media=${encodeURIComponent(filename)}&tab=${
                                str(row, "media_type") === "image" ? "image" : "video"
                              }`
                            )
                          }
                        >
                          В библиотеке
                        </button>
                      ) : null}
                    </li>
                  );
                })
              : null}
          </ul>
          {block.items.length > INITIAL_VISIBLE ? (
            <button
              type="button"
              className="btn-ghost mt-2 w-full min-h-9 text-[11px]"
              data-testid={`assistant-cards-expand-${block.kind}`}
              onClick={onToggleExpand}
            >
              {expanded ? "Свернуть" : `Показать ещё ${hiddenCount}`}
            </button>
          ) : null}
        </>
      )}
    </section>
  );
}

export function AssistantCards({ blocks, onNavigate, onOpenAccount, onOpenBrowser }: Props) {
  const [expandedKinds, setExpandedKinds] = useState<Record<string, boolean>>({});
  if (!blocks.length) return null;

  return (
    <div className="mt-2 space-y-3" data-testid="assistant-cards">
      {blocks.map((block) => (
        <CardSection
          key={block.kind}
          block={block}
          expanded={Boolean(expandedKinds[block.kind])}
          onToggleExpand={() =>
            setExpandedKinds((prev) => ({ ...prev, [block.kind]: !prev[block.kind] }))
          }
          onNavigate={onNavigate}
          onOpenAccount={onOpenAccount}
          onOpenBrowser={onOpenBrowser}
        />
      ))}
    </div>
  );
}

export function mergeCardBlocks(
  current: AssistantCardBlock[],
  incoming: AssistantCardBlock[]
): AssistantCardBlock[] {
  const map = new Map(current.map((b) => [b.kind, b]));
  for (const block of incoming) {
    map.set(block.kind, block);
  }
  const order: AssistantCardBlock["kind"][] = ["accounts", "renders", "clips"];
  return order.filter((k) => map.has(k)).map((k) => map.get(k)!);
}

export const LIST_CARD_TOOL_NAMES = new Set(["list_accounts", "list_renders", "list_clips"]);
