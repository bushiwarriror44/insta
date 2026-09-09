import clsx from "clsx";
import { Download, Film, ImageIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { fetchMediaObjectUrl, formatBytes, formatDuration, revokeMediaObjectUrl } from "../api/media";
import type { VideoOut } from "../api/types";
import { useHotkeys } from "../hooks/useHotkeys";

function MediaThumb({ item }: { item: VideoOut }) {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;
    fetchMediaObjectUrl(item.filename)
      .then((u) => {
        if (cancelled) {
          revokeMediaObjectUrl(u);
          return;
        }
        objectUrl = u;
        setUrl(u);
      })
      .catch(() => {
        if (!cancelled) setUrl(null);
      });
    return () => {
      cancelled = true;
      revokeMediaObjectUrl(objectUrl);
    };
  }, [item.filename]);

  if (item.media_type === "video" && url) {
    return (
      <video
        src={url}
        className="absolute inset-0 h-full w-full object-cover"
        muted
        playsInline
        preload="metadata"
      />
    );
  }
  if (item.media_type === "image" && url) {
    return (
      <img src={url} alt="" className="absolute inset-0 h-full w-full object-cover" />
    );
  }
  return (
    <div className="absolute inset-0 flex items-center justify-center bg-slate-800">
      {item.media_type === "video" ? (
        <Film size={28} className="text-slate-500" />
      ) : (
        <ImageIcon size={28} className="text-slate-500" />
      )}
    </div>
  );
}

interface Props {
  items: VideoOut[];
  selectedFilename: string | null;
  checkedFilenames: Set<string>;
  tab: "video" | "image";
  search: string;
  archiveBusy?: boolean;
  onTabChange: (tab: "video" | "image") => void;
  onSearchChange: (value: string) => void;
  onSelect: (item: VideoOut) => void;
  onToggleChecked: (filename: string) => void;
  onClearChecked: () => void;
  onDownloadArchive: () => void;
  onQuickPublish: (item: VideoOut) => void;
  quickPublishDisabled?: boolean;
}

export function MediaLibraryGrid({
  items,
  selectedFilename,
  checkedFilenames,
  tab,
  search,
  archiveBusy,
  onTabChange,
  onSearchChange,
  onSelect,
  onToggleChecked,
  onClearChecked,
  onDownloadArchive,
  onQuickPublish,
  quickPublishDisabled,
}: Props) {
  const filtered = items.filter((item) => {
    if (item.media_type !== tab) return false;
    if (!search.trim()) return true;
    return item.filename.toLowerCase().includes(search.trim().toLowerCase());
  });

  const libraryKeys = useMemo(
    () => ({
      j: () => {
        if (!filtered.length) return;
        const i = filtered.findIndex((item) => item.filename === selectedFilename);
        const next = filtered[Math.min((i < 0 ? -1 : i) + 1, filtered.length - 1)];
        if (next) onSelect(next);
      },
      k: () => {
        if (!filtered.length) return;
        const i = filtered.findIndex((item) => item.filename === selectedFilename);
        const next = filtered[Math.max((i < 0 ? 0 : i) - 1, 0)];
        if (next) onSelect(next);
      },
    }),
    [filtered, onSelect, selectedFilename]
  );
  useHotkeys(libraryKeys);

  const checkedCount = checkedFilenames.size;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex gap-1 p-1 rounded-lg bg-slate-900/60 border border-slate-800">
          <button
            type="button"
            className={clsx(
              "text-xs px-3 py-1.5 rounded-md font-medium",
              tab === "video"
                ? "bg-slate-800 text-white"
                : "text-slate-400 hover:text-slate-200"
            )}
            aria-label="Вкладка видео"
            onClick={() => onTabChange("video")}
          >
            Видео
          </button>
          <button
            type="button"
            className={clsx(
              "text-xs px-3 py-1.5 rounded-md font-medium",
              tab === "image"
                ? "bg-slate-800 text-white"
                : "text-slate-400 hover:text-slate-200"
            )}
            aria-label="Вкладка фото"
            onClick={() => onTabChange("image")}
          >
            Фото
          </button>
        </div>
        <input
          className="input flex-1 min-w-[10rem] text-sm py-1.5"
          data-page-search
          aria-label="Поиск по имени файла"
          placeholder="Поиск по имени файла…"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
        />
      </div>

      {checkedCount > 0 ? (
        <div className="flex flex-wrap items-center gap-2 text-sm text-slate-300">
          <span>Выбрано: {checkedCount}</span>
          <button type="button" className="btn-ghost text-xs py-1" onClick={onClearChecked}>
            Снять выбор
          </button>
          <button
            type="button"
            className="btn-primary text-xs py-1"
            disabled={archiveBusy}
            onClick={onDownloadArchive}
          >
            <Download size={14} className={archiveBusy ? "animate-pulse" : ""} />
            {archiveBusy ? "Скачивание…" : "Скачать ZIP"}
          </button>
        </div>
      ) : null}

      {filtered.length === 0 ? (
        <div className="text-sm text-slate-500 py-8 text-center rounded-xl border border-dashed border-slate-800">
          {tab === "video"
            ? "Видео пока нет — перетащите готовые Reels (.mp4) выше."
            : "Фото пока нет — загрузите .jpg / .png / .webp."}
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-2 xl:grid-cols-3 gap-3 max-h-[32rem] overflow-y-auto pr-1">
          {filtered.map((item) => {
            const selected = item.filename === selectedFilename;
            const checked = checkedFilenames.has(item.filename);
            return (
              <div
                key={item.filename}
                role="button"
                tabIndex={0}
                className={clsx(
                  "group relative rounded-xl border bg-slate-950/50 overflow-hidden text-left transition-all",
                  "hover:border-brand-500/50 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500",
                  selected ? "border-brand-500 ring-2 ring-brand-500/40" : "border-slate-800"
                )}
                onClick={() => onSelect(item)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onSelect(item);
                  }
                }}
              >
                <div className="relative aspect-[9/16] bg-slate-900">
                  <MediaThumb item={item} />
                  <label
                    className="absolute top-1.5 right-1.5 z-10 flex h-6 w-6 items-center justify-center rounded bg-black/60"
                    onClick={(e) => e.stopPropagation()}
                    onKeyDown={(e) => e.stopPropagation()}
                  >
                    <input
                      type="checkbox"
                      className="rounded border-slate-500 bg-slate-900"
                      checked={checked}
                      aria-label={`Выбрать ${item.filename}`}
                      onChange={() => onToggleChecked(item.filename)}
                    />
                  </label>
                  <span className="absolute top-1.5 left-1.5 text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-black/60 text-slate-200">
                    {item.media_type === "video" ? "видео" : "фото"}
                  </span>
                  {item.duration_sec ? (
                    <span className="absolute bottom-1.5 right-1.5 text-[10px] px-1.5 py-0.5 rounded bg-black/70 text-white tabular-nums">
                      {formatDuration(item.duration_sec)}
                    </span>
                  ) : null}
                </div>
                <div className="p-2 space-y-1">
                  <div className="text-xs font-medium truncate" title={item.filename}>
                    {item.filename}
                  </div>
                  <div className="text-[10px] text-slate-500 flex justify-between gap-1">
                    <span>{formatBytes(item.size_bytes)}</span>
                    <span>{new Date(item.modified_at).toLocaleDateString("ru-RU")}</span>
                  </div>
                  <button
                    type="button"
                    className="btn-ghost text-[10px] w-full py-1 opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity"
                    disabled={quickPublishDisabled}
                    aria-label={`Быстрая публикация ${item.filename}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      onQuickPublish(item);
                    }}
                  >
                    Быстрая публикация
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
