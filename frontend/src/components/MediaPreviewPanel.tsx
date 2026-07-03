import { Calendar, Send, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import { fetchMediaObjectUrl, formatBytes, formatDuration, revokeMediaObjectUrl } from "../api/media";
import type { AccountOut, PostType, VideoOut } from "../api/types";

const POST_TYPES: Array<{ value: PostType; label: string; media: "image" | "video" }> = [
  { value: "reel", label: "Reels", media: "video" },
  { value: "feed_photo", label: "Feed photo", media: "image" },
  { value: "feed_video", label: "Feed video", media: "video" },
];

interface Props {
  item: VideoOut | null;
  accounts: AccountOut[];
  username: string;
  postType: PostType;
  whenLocal: string;
  caption: string;
  saving: boolean;
  onUsernameChange: (value: string) => void;
  onPostTypeChange: (value: PostType) => void;
  onWhenChange: (value: string) => void;
  onCaptionChange: (value: string) => void;
  onPublish: () => void;
  onDelete: () => void;
}

export function MediaPreviewPanel({
  item,
  accounts,
  username,
  postType,
  whenLocal,
  caption,
  saving,
  onUsernameChange,
  onPostTypeChange,
  onWhenChange,
  onCaptionChange,
  onPublish,
  onDelete,
}: Props) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!item) {
      setBlobUrl(null);
      return;
    }
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
        Select a video or photo from the library to preview and publish.
      </div>
    );
  }

  const compatibleTypes = POST_TYPES.filter((p) => p.media === item.media_type);

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
          <div className="text-slate-500 text-sm py-12">Preview unavailable</div>
        )}
      </div>

      <div className="text-sm space-y-1">
        <div className="font-medium break-all">{item.filename}</div>
        <div className="text-xs text-slate-500 flex flex-wrap gap-x-3 gap-y-1">
          <span>{formatBytes(item.size_bytes)}</span>
          {item.duration_sec ? <span>{formatDuration(item.duration_sec)}</span> : null}
          <span>{new Date(item.modified_at).toLocaleString()}</span>
        </div>
      </div>

      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          onPublish();
        }}
      >
        <div>
          <label className="label">Account</label>
          <select
            className="input"
            value={username}
            onChange={(e) => onUsernameChange(e.target.value)}
          >
            {accounts.map((a) => (
              <option key={a.id} value={a.username}>
                @{a.username} — {a.status}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label">Post type</label>
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
          <label className="label">Schedule for (optional)</label>
          <div className="relative">
            <input
              type="datetime-local"
              className="input pl-9"
              value={whenLocal}
              onChange={(e) => onWhenChange(e.target.value)}
            />
            <Calendar size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          </div>
          <div className="text-xs text-slate-500 mt-1">Leave empty to publish ASAP.</div>
        </div>
        <div>
          <label className="label">Caption</label>
          <textarea
            className="input min-h-[72px]"
            value={caption}
            onChange={(e) => onCaptionChange(e.target.value)}
            placeholder="Optional caption. Reels support {hashtags}, {emoji}."
          />
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            className="btn-ghost text-rose-300 shrink-0"
            onClick={onDelete}
          >
            <Trash2 size={16} /> Delete
          </button>
          <button
            type="submit"
            className="btn-primary flex-1"
            disabled={saving || accounts.length === 0}
          >
            <Send size={16} />
            {saving ? "Publishing…" : whenLocal ? "Schedule" : "Publish now"}
          </button>
        </div>
      </form>
    </div>
  );
}
