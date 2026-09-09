import { BarChart3, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { api, formatApiError } from "../api/client";
import { Card } from "../components/Card";
import { DropZone } from "../components/DropZone";
import { Loader } from "../components/Loader";
import { MediaLibraryGrid } from "../components/MediaLibraryGrid";
import { MediaPreviewPanel } from "../components/MediaPreviewPanel";
import { useToast } from "../context/ToastContext";
import { useAssistantMutate } from "../lib/assistantMutate";
import type { AccountOut, PostType, PublicationOut, VideoOut } from "../api/types";

type UploadQueueItem = {
  id: string;
  name: string;
  pct: number;
  status: "pending" | "uploading" | "done" | "error";
  error?: string;
};

function count(v: number | null | undefined) {
  return v == null ? "-" : v.toLocaleString("ru-RU");
}

const POST_TYPE_LABELS: Record<string, string> = {
  reel: "Reels",
  feed_photo: "Фото в ленте",
  feed_video: "Видео в ленте",
  youtube_short: "YouTube Shorts",
  tiktok: "TikTok",
};

function basename(path: string | null) {
  if (!path) return "-";
  return path.split(/[\\/]/).pop() || path;
}

function defaultPostTypeForItem(item: VideoOut): PostType {
  if (item.media_type === "image") return "feed_photo";
  return "reel";
}

function mergeLibrary(uploads: VideoOut[], generated: VideoOut[]): VideoOut[] {
  const known = new Set(uploads.map((item) => item.filename));
  return [...uploads, ...generated.filter((item) => !known.has(item.filename))];
}

async function fetchGeneratedVideos(): Promise<VideoOut[]> {
  try {
    const assets = await api.factory.assets({ kind: "video" });
    return assets.map((asset) => ({
      filename: asset.filename,
      size_bytes: 0,
      modified_at: asset.created_at,
      media_type: "video" as const,
      duration_sec: asset.duration_s,
    }));
  } catch {
    return [];
  }
}

async function fetchLibraryMedia(): Promise<VideoOut[]> {
  const [uploads, generated] = await Promise.all([api.videos.list(), fetchGeneratedVideos()]);
  return mergeLibrary(uploads, generated);
}

export function Publishing() {
  const { push } = useToast();
  const [accounts, setAccounts] = useState<AccountOut[]>([]);
  const [media, setMedia] = useState<VideoOut[]>([]);
  const [publications, setPublications] = useState<PublicationOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [refreshingId, setRefreshingId] = useState<number | null>(null);
  const [username, setUsername] = useState("");
  const [postType, setPostType] = useState<PostType>("reel");
  const [selectedFilename, setSelectedFilename] = useState<string | null>(null);
  const [libraryTab, setLibraryTab] = useState<"video" | "image">("video");
  const [search, setSearch] = useState("");
  const [whenLocal, setWhenLocal] = useState("");
  const [caption, setCaption] = useState("");
  const [skipImageCompress, setSkipImageCompress] = useState(false);
  const [checkedFilenames, setCheckedFilenames] = useState<Set<string>>(() => new Set());
  const [archiveBusy, setArchiveBusy] = useState(false);
  const [downloadBusy, setDownloadBusy] = useState(false);
  const [uploadQueue, setUploadQueue] = useState<UploadQueueItem[]>([]);
  const [generatePrompt, setGeneratePrompt] = useState("");
  const [joinIds, setJoinIds] = useState("");

  const selectedItem = useMemo(
    () => media.find((m) => m.filename === selectedFilename) ?? null,
    [media, selectedFilename]
  );

  const defaultUsername = useMemo(
    () => accounts.find((a) => a.status === "active")?.username ?? accounts[0]?.username ?? "",
    [accounts]
  );

  const reload = useCallback(async () => {
    const [a, m, p, generated] = await Promise.all([
      api.accounts.list(),
      api.videos.list(),
      api.publications.list({ limit: 100 }),
      fetchGeneratedVideos(),
    ]);
    setAccounts(a);
    setMedia(mergeLibrary(m, generated));
    setPublications(p);
    setUsername((current) => current || defaultUsername || a[0]?.username || "");
  }, [defaultUsername]);

  useAssistantMutate(reload);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await reload();
      } catch (err) {
        push((err as Error).message, "error");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [push, reload]);

  useEffect(() => {
    if (!selectedFilename && media.length > 0) {
      const firstVideo = media.find((m) => m.media_type === "video");
      const pick = firstVideo ?? media[0];
      setSelectedFilename(pick.filename);
      setLibraryTab(pick.media_type);
      setPostType(defaultPostTypeForItem(pick));
    }
  }, [media, selectedFilename]);

  useEffect(() => {
    const known = new Set(media.map((m) => m.filename));
    setCheckedFilenames((prev) => {
      let changed = false;
      const next = new Set<string>();
      for (const name of prev) {
        if (known.has(name)) next.add(name);
        else changed = true;
      }
      return changed || next.size !== prev.size ? next : prev;
    });
  }, [media]);

  function selectItem(item: VideoOut) {
    setSelectedFilename(item.filename);
    setLibraryTab(item.media_type);
    setPostType(defaultPostTypeForItem(item));
  }

  function toggleChecked(filename: string) {
    setCheckedFilenames((prev) => {
      const next = new Set(prev);
      if (next.has(filename)) next.delete(filename);
      else next.add(filename);
      return next;
    });
  }

  async function downloadSelectedArchive() {
    const filenames = Array.from(checkedFilenames);
    if (filenames.length === 0) return;
    setArchiveBusy(true);
    try {
      await api.videos.downloadArchive(filenames);
      push(`Скачан ZIP (${filenames.length})`, "success");
    } catch (err) {
      push((err as Error).message, "error");
    } finally {
      setArchiveBusy(false);
    }
  }

  async function downloadSelectedFile() {
    if (!selectedFilename) return;
    setDownloadBusy(true);
    try {
      await api.videos.download(selectedFilename);
      push("Файл скачан", "success");
    } catch (err) {
      push((err as Error).message, "error");
    } finally {
      setDownloadBusy(false);
    }
  }

  async function uploadFiles(files: File[]) {
    if (files.length === 0) return;
    const queue: UploadQueueItem[] = files.map((file, index) => ({
      id: `${file.name}-${file.size}-${index}-${Date.now()}`,
      name: file.name,
      pct: 0,
      status: "pending",
    }));
    setUploadQueue(queue);
    setUploading(true);

    let last: VideoOut | null = null;
    let okCount = 0;
    const errors: string[] = [];

    try {
      for (let i = 0; i < files.length; i++) {
        const file = files[i];
        const itemId = queue[i].id;
        setUploadQueue((prev) =>
          prev.map((row) =>
            row.id === itemId ? { ...row, status: "uploading", pct: 0, error: undefined } : row
          )
        );
        try {
          const out = await api.videos.upload(file, {
            compress: !skipImageCompress,
            onProgress: (loaded, total) => {
              const pct = total > 0 ? Math.min(100, Math.round((loaded / total) * 100)) : 0;
              setUploadQueue((prev) =>
                prev.map((row) => (row.id === itemId ? { ...row, pct } : row))
              );
            },
          });
          okCount += 1;
          last = {
            filename: out.filename,
            size_bytes: out.size_bytes,
            modified_at: new Date().toISOString(),
            media_type: out.media_type,
            duration_sec: out.duration_sec,
          };
          setUploadQueue((prev) =>
            prev.map((row) =>
              row.id === itemId ? { ...row, status: "done", pct: 100 } : row
            )
          );
        } catch (err) {
          const message = formatApiError(err);
          errors.push(`${file.name}: ${message}`);
          setUploadQueue((prev) =>
            prev.map((row) =>
              row.id === itemId ? { ...row, status: "error", error: message } : row
            )
          );
        }
      }

      try {
        setMedia(await fetchLibraryMedia());
      } catch (err) {
        push(formatApiError(err), "error");
      }

      if (last) selectItem(last);

      if (okCount === files.length) {
        push(
          files.length === 1
            ? `Загружено: ${last?.filename ?? files[0].name}`
            : `Загружено файлов: ${okCount}`,
          "success"
        );
      } else if (okCount > 0) {
        push(`Загружено ${okCount} из ${files.length}. ${errors[0] ?? ""}`.trim(), "error");
      } else {
        push(errors[0] ?? "Не удалось загрузить файлы", "error");
      }
    } finally {
      setUploading(false);
    }
  }

  async function enqueuePublication(opts?: {
    mediaFilename?: string;
    postTypeOverride?: PostType;
    usernameOverride?: string;
    captionOverride?: string | null;
    whenOverride?: string | null;
    title?: string;
    description?: string;
    tags?: string;
  }) {
    const mediaFilename = opts?.mediaFilename ?? selectedFilename;
    const account = opts?.usernameOverride ?? username;
    if (!account || !mediaFilename) {
      push("Выберите аккаунт и медиафайл", "error");
      return;
    }
    const type = opts?.postTypeOverride ?? postType;
    setSaving(true);
    try {
      const whenIso = opts?.whenOverride !== undefined
        ? opts.whenOverride
        : whenLocal
          ? new Date(whenLocal).toISOString()
          : null;
      await api.jobs.enqueue({
        username: account,
        media_filename: mediaFilename,
        post_type: type,
        caption_template: opts?.captionOverride !== undefined
          ? opts.captionOverride
          : caption.trim()
            ? caption
            : null,
        title: opts?.title || null,
        description: opts?.description || null,
        tags: opts?.tags || null,
        when: whenIso,
      });
      push(whenIso ? "Публикация запланирована" : "Публикация добавлена в очередь", "success", {
        label: "Открыть",
        href: "/activity",
      });
      setCaption("");
      setWhenLocal("");
      await reload();
    } catch (err) {
      push((err as Error).message, "error");
    } finally {
      setSaving(false);
    }
  }

  async function quickPublish(item: VideoOut) {
    const account = username || defaultUsername;
    if (!account) {
      push("Сначала добавьте аккаунт", "error");
      return;
    }
    selectItem(item);
    await enqueuePublication({
      mediaFilename: item.filename,
      postTypeOverride: defaultPostTypeForItem(item),
      usernameOverride: account,
      captionOverride: null,
      whenOverride: null,
    });
  }

  async function deleteSelected() {
    if (!selectedFilename) return;
    if (!window.confirm(`Удалить ${selectedFilename}?`)) return;
    try {
      await api.videos.remove(selectedFilename);
      push("Медиафайл удалён", "info");
      const list = await fetchLibraryMedia();
      setMedia(list);
      if (list[0]) {
        selectItem(list[0]);
      } else {
        setSelectedFilename(null);
        setLibraryTab("video");
        setPostType("reel");
      }
    } catch (err) {
      push((err as Error).message, "error");
    }
  }

  async function refreshStats(row: PublicationOut) {
    setRefreshingId(row.id);
    try {
      const updated = await api.publications.refreshStats(row.id);
      setPublications((items) => items.map((item) => (item.id === updated.id ? updated : item)));
      push("Статистика обновлена", "success");
    } catch (err) {
      push((err as Error).message, "error");
    } finally {
      setRefreshingId(null);
    }
  }

  if (loading) return <Loader />;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Библиотека</h1>
        <p className="text-sm text-slate-400 mt-1">
          Загружайте готовые Reels, просматривайте в браузере и публикуйте в один клик.
        </p>
      </div>
      <Card className="p-4 space-y-3">
        <h2 className="font-medium">Сгенерировать / склеить</h2>
        <div className="flex gap-2">
          <input className="input" placeholder="Промпт для fal.ai" value={generatePrompt} onChange={(e) => setGeneratePrompt(e.target.value)} />
          <button
            className="btn-primary shrink-0"
            disabled={!generatePrompt.trim()}
            onClick={async () => {
              try {
                await api.factory.createGeneration({ prompt: generatePrompt.trim() });
                setGeneratePrompt("");
                push("Рендер в очереди", "success", { label: "Открыть", href: "/renders" });
              } catch (err) {
                push(formatApiError(err), "error");
              }
            }}
          >
            Рендер
          </button>
        </div>
        <div className="flex gap-2">
          <input className="input" placeholder="id клипов через запятую" value={joinIds} onChange={(e) => setJoinIds(e.target.value)} />
          <button
            className="btn-ghost shrink-0"
            onClick={async () => {
              const clip_ids = joinIds.split(",").map((s) => Number(s.trim())).filter(Boolean);
              if (!clip_ids.length) return;
              try {
                await api.factory.createComposition({ clip_ids });
                setJoinIds("");
                push("Склейка в очереди", "success", { label: "Открыть", href: "/renders" });
              } catch (err) {
                push(formatApiError(err), "error");
              }
            }}
          >
            Склеить
          </button>
        </div>
      </Card>

      <Card title="Загрузка в библиотеку">
        <DropZone
          accept="video/mp4,video/quicktime,video/x-m4v,image/jpeg,image/png,image/webp"
          disabled={uploading}
          staging
          multiple
          title="Перетащите готовые Reels (.mp4)"
          hint=".mp4 / .mov / фото — до 512 МБ"
          onFile={(file) => uploadFiles([file])}
          onFiles={uploadFiles}
        />
        <label className="mt-3 flex items-center gap-2 text-sm text-slate-400 cursor-pointer select-none">
          <input
            type="checkbox"
            className="rounded border-slate-600 bg-slate-900"
            checked={skipImageCompress}
            disabled={uploading}
            onChange={(e) => setSkipImageCompress(e.target.checked)}
          />
          Не сжимать
        </label>
        {uploadQueue.length > 0 ? (
          <ul className="mt-3 space-y-2" aria-label="Очередь загрузки">
            {uploadQueue.map((item) => (
              <li key={item.id} className="text-xs text-slate-300 space-y-1">
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate font-mono" title={item.name}>
                    {item.name}
                  </span>
                  <span className="shrink-0 tabular-nums text-slate-400">
                    {item.status === "pending"
                      ? "ожидание"
                      : item.status === "uploading"
                        ? `${item.pct}%`
                        : item.status === "done"
                          ? "готово"
                          : "ошибка"}
                  </span>
                </div>
                <div className="h-1.5 rounded-full bg-slate-800 overflow-hidden">
                  <div
                    className={
                      item.status === "error"
                        ? "h-full bg-rose-500 transition-[width]"
                        : item.status === "done"
                          ? "h-full bg-emerald-500 transition-[width]"
                          : "h-full bg-brand-500 transition-[width]"
                    }
                    style={{
                      width: `${
                        item.status === "pending"
                          ? 0
                          : item.status === "error"
                            ? Math.max(item.pct, 8)
                            : item.pct
                      }%`,
                    }}
                  />
                </div>
                {item.error ? (
                  <p className="text-rose-300 break-words">{item.error}</p>
                ) : null}
              </li>
            ))}
          </ul>
        ) : uploading ? (
          <div className="text-xs text-slate-400 mt-2">Загрузка…</div>
        ) : null}
      </Card>

      <div className="grid grid-cols-1 xl:grid-cols-5 gap-4">
        <Card
          title="Медиатека"
          description={`${media.length} файлов`}
          className="xl:col-span-3"
        >
          <MediaLibraryGrid
            items={media}
            selectedFilename={selectedFilename}
            checkedFilenames={checkedFilenames}
            tab={libraryTab}
            search={search}
            archiveBusy={archiveBusy}
            onTabChange={setLibraryTab}
            onSearchChange={setSearch}
            onSelect={selectItem}
            onToggleChecked={toggleChecked}
            onClearChecked={() => setCheckedFilenames(new Set())}
            onDownloadArchive={downloadSelectedArchive}
            onQuickPublish={quickPublish}
            quickPublishDisabled={saving || accounts.length === 0}
          />
        </Card>

        <Card title="Просмотр и публикация" className="xl:col-span-2">
          <MediaPreviewPanel
            item={selectedItem}
            accounts={accounts}
            username={username}
            postType={postType}
            whenLocal={whenLocal}
            caption={caption}
            saving={saving}
            downloadBusy={downloadBusy}
            onUsernameChange={setUsername}
            onPostTypeChange={setPostType}
            onWhenChange={setWhenLocal}
            onCaptionChange={setCaption}
            onPublish={(meta) => enqueuePublication(meta)}
            onDelete={deleteSelected}
            onDownload={downloadSelectedFile}
          />
        </Card>
      </div>

      <Card title="Статистика опубликованных медиа" description={`${publications.length} записей`}>
        {publications.length === 0 ? (
          <div className="text-sm text-slate-500">Публикаций пока нет.</div>
        ) : (
          <table className="table-base">
            <colgroup>
              <col className="w-[12%]" />
              <col className="w-[10%]" />
              <col className="w-[16%]" />
              <col className="w-[10%]" />
              <col className="w-[16%]" />
              <col className="w-[22%]" />
              <col className="w-[14%]" />
            </colgroup>
            <thead>
              <tr>
                <th>Аккаунт</th>
                <th>Тип</th>
                <th>Медиа</th>
                <th>Статус</th>
                <th>Ошибка</th>
                <th>Статистика</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {publications.map((row) => (
                <tr key={row.id} className="hover:bg-slate-900/40">
                  <td className="font-medium truncate" title={`@${row.account_username ?? row.account_id}`}>
                    @{row.account_username ?? row.account_id}
                  </td>
                  <td className="text-slate-300 truncate">
                    {POST_TYPE_LABELS[row.post_type ?? "reel"] ?? row.post_type ?? "reel"}
                  </td>
                  <td className="text-[11px] text-slate-400 min-w-0">
                    <div className="truncate" title={row.media_code ?? row.media_id ?? "-"}>
                      {row.media_code ?? row.media_id ?? "-"}
                    </div>
                    <div className="truncate text-slate-500" title={basename(row.final_media_path)}>
                      {basename(row.final_media_path)}
                    </div>
                  </td>
                  <td className={row.success ? "text-emerald-300" : "text-rose-300"}>
                    {row.success ? "опубликовано" : "ошибка"}
                  </td>
                  <td className="text-[11px] text-rose-300 truncate" title={row.error ?? "—"}>
                    {row.error ?? "—"}
                  </td>
                  <td className="tabular-nums text-[11px] text-slate-300">
                    <div>
                      {count(row.view_count)} / {count(row.play_count)}
                    </div>
                    <div>{count(row.like_count)}</div>
                    <div>{count(row.comment_count)}</div>
                    <div>
                      {count(row.save_count)} / {count(row.share_count)}
                    </div>
                    <div
                      className="truncate text-slate-500"
                      title={row.last_stats_at ? new Date(row.last_stats_at).toLocaleString("ru-RU") : "-"}
                    >
                      {row.last_stats_at ? new Date(row.last_stats_at).toLocaleString("ru-RU") : "-"}
                    </div>
                  </td>
                  <td className="text-right">
                    <button
                      type="button"
                      className="btn-ghost btn-compact"
                      aria-label="Обновить статистику"
                      disabled={!row.success || !row.media_id || refreshingId === row.id}
                      onClick={() => refreshStats(row)}
                    >
                      {refreshingId === row.id ? (
                        <RefreshCw size={14} className="animate-spin" />
                      ) : (
                        <BarChart3 size={14} />
                      )}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
