import { Calendar, Download, Send, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import { fetchMediaObjectUrl, formatBytes, formatDuration, revokeMediaObjectUrl } from "../api/media";
import type { AccountOut, PostType, VideoOut } from "../api/types";

const POST_TYPES: Array<{ value: PostType; label: string; media: "image" | "video" }> = [
  { value: "reel", label: "Reels", media: "video" },
  { value: "youtube_short", label: "YouTube Shorts", media: "video" },
  { value: "tiktok", label: "TikTok", media: "video" },
  { value: "feed_photo", label: "Фото в ленте", media: "image" },
  { value: "feed_video", label: "Видео в ленте", media: "video" },
];

const ACCOUNT_STATUS_LABELS: Record<string, string> = {
  active: "активен",
  inactive: "неактивен",
  banned: "заблокирован",
  error: "ошибка",
};

interface Props {
  item: VideoOut | null;
  accounts: AccountOut[];
  username: string;
  postType: PostType;
  whenLocal: string;
  caption: string;
  saving: boolean;
  downloadBusy?: boolean;
  onUsernameChange: (value: string) => void;
  onPostTypeChange: (value: PostType) => void;
  onWhenChange: (value: string) => void;
  onCaptionChange: (value: string) => void;
  onPublish: (meta?: { title?: string; description?: string; tags?: string }) => void;
  onDelete: () => void;
  onDownload: () => void;
}

export function MediaPreviewPanel({
  item,
  accounts,
  username,
  postType,
  whenLocal,
  caption,
  saving,
  downloadBusy,
  onUsernameChange,
  onPostTypeChange,
  onWhenChange,
  onCaptionChange,
  onPublish,
  onDelete,
  onDownload,
}: Props) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [tags, setTags] = useState("");

  useEffect(() => {
    if (!item) {
      setBlobUrl(null);
      return;
    }
    setBlobUrl(null);
    let cancelled = false;
    let objectUrl: string | null = null;
    fetchMediaObjectUrl(item.filename)
      .then((u) => {
        if (cancelled) {
          revokeMediaObjectUrl(u);
          return;
        }
        objectUrl = u;
        setBlobUrl(u);
      })
      .catch(() => {
        if (!cancelled) setBlobUrl(null);
      });
    return () => {
      cancelled = true;
      revokeMediaObjectUrl(objectUrl);
    };
  }, [item?.filename]);

  if (!item) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[20rem] text-center text-slate-500 text-sm px-4">
        Выберите видео или фото из библиотеки для просмотра и публикации.
      </div>
    );
  }

  const compatibleTypes = POST_TYPES.filter((p) => p.media === item.media_type);
  const needsCopy = postType === "youtube_short" || postType === "tiktok";

  return (
    <div className="space-y-4">
      <div className="flex justify-center rounded-xl bg-slate-950 border border-slate-800 p-3">
        {item.media_type === "video" && blobUrl ? (
          <video
            src={blobUrl}
            className="max-h-72 w-full max-w-[12rem] aspect-[9/16] object-contain bg-black rounded-lg"
            controls
            playsInline
            preload="metadata"
          />
        ) : item.media_type === "image" && blobUrl ? (
          <img
            src={blobUrl}
            alt={item.filename}
            className="max-h-72 rounded-lg object-contain"
          />
        ) : (
          <div className="text-slate-500 text-sm py-12">Предпросмотр недоступен</div>
        )}
      </div>

      <div className="text-sm space-y-1">
        <div className="font-medium break-all">{item.filename}</div>
        <div className="text-xs text-slate-500 flex flex-wrap gap-x-3 gap-y-1">
          <span>{formatBytes(item.size_bytes)}</span>
          {item.duration_sec ? <span>{formatDuration(item.duration_sec)}</span> : null}
          <span>{new Date(item.modified_at).toLocaleString("ru-RU")}</span>
        </div>
      </div>

      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          onPublish(needsCopy ? { title, description, tags } : undefined);
        }}
      >
        <div>
          <label className="label">Аккаунт</label>
          <select
            className="input"
            value={username}
            onChange={(e) => onUsernameChange(e.target.value)}
          >
            {accounts.map((a) => (
              <option key={a.id} value={a.username}>
                @{a.username} · {a.platform || "instagram"} — {ACCOUNT_STATUS_LABELS[a.status] ?? a.status}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label">Тип публикации</label>
          <select
            className="input"
            value={postType}
            onChange={(e) => onPostTypeChange(e.target.value as PostType)}
          >
            {compatibleTypes.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label">Запланировать на (необязательно)</label>
          <div className="relative">
            <input
              type="datetime-local"
              className="input pl-9"
              value={whenLocal}
              onChange={(e) => onWhenChange(e.target.value)}
            />
            <Calendar size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          </div>
          <div className="text-xs text-slate-500 mt-1">Оставьте пустым для немедленной публикации.</div>
        </div>
        {needsCopy ? (
          <>
            <div>
              <label className="label">Заголовок</label>
              <input
                className="input"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Название Shorts / TikTok"
              />
            </div>
            <div>
              <label className="label">Описание</label>
              <textarea
                className="input min-h-[72px]"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>
            <div>
              <label className="label">Теги</label>
              <input
                className="input"
                value={tags}
                onChange={(e) => setTags(e.target.value)}
                placeholder="nature, calm"
              />
            </div>
          </>
        ) : (
          <div>
            <label className="label">Подпись</label>
            <textarea
              className="input min-h-[72px]"
              value={caption}
              onChange={(e) => onCaptionChange(e.target.value)}
              placeholder="Подпись (необязательно). Для Reels поддерживаются {hashtags}, {emoji}."
            />
          </div>
        )}
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="btn-ghost text-rose-300 shrink-0"
            onClick={onDelete}
          >
            <Trash2 size={16} /> Удалить
          </button>
          <button
            type="button"
            className="btn-ghost shrink-0"
            disabled={downloadBusy}
            onClick={onDownload}
          >
            <Download size={16} className={downloadBusy ? "animate-pulse" : ""} />
            {downloadBusy ? "Скачивание…" : "Скачать"}
          </button>
          <button
            type="submit"
            className="btn-primary flex-1 min-w-[8rem]"
            disabled={saving || accounts.length === 0}
          >
            <Send size={16} />
            {saving ? "Публикация…" : whenLocal ? "Запланировать" : "Опубликовать сейчас"}
          </button>
        </div>
      </form>
    </div>
  );
}
