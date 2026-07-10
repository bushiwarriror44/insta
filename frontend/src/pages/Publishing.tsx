import { BarChart3, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "../api/client";
import { Card } from "../components/Card";
import { DropZone } from "../components/DropZone";
import { Loader } from "../components/Loader";
import { MediaLibraryGrid } from "../components/MediaLibraryGrid";
import { MediaPreviewPanel } from "../components/MediaPreviewPanel";
import { useToast } from "../context/ToastContext";
import type { AccountOut, PostType, PublicationOut, VideoOut } from "../api/types";

function count(v: number | null | undefined) {
  return v == null ? "-" : v.toLocaleString("ru-RU");
}

const POST_TYPE_LABELS: Record<string, string> = {
  reel: "Reels",
  feed_photo: "Фото в ленте",
  feed_video: "Видео в ленте",
};

function basename(path: string | null) {
  if (!path) return "-";
  return path.split(/[\\/]/).pop() || path;
}

function defaultPostTypeForItem(item: VideoOut): PostType {
  if (item.media_type === "image") return "feed_photo";
  return "reel";
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

  const selectedItem = useMemo(
    () => media.find((m) => m.filename === selectedFilename) ?? null,
    [media, selectedFilename]
  );

  const defaultUsername = useMemo(
    () => accounts.find((a) => a.status === "active")?.username ?? accounts[0]?.username ?? "",
    [accounts]
  );

  const reload = useCallback(async () => {
    const [a, m, p] = await Promise.all([
      api.accounts.list(),
      api.videos.list(),
      api.publications.list({ limit: 100 }),
    ]);
    setAccounts(a);
    setMedia(m);
    setPublications(p);
    setUsername((current) => current || defaultUsername || a[0]?.username || "");
  }, [defaultUsername]);

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

  function selectItem(item: VideoOut) {
    setSelectedFilename(item.filename);
    setLibraryTab(item.media_type);
    setPostType(defaultPostTypeForItem(item));
  }

  async function uploadFiles(files: File[]) {
    if (files.length === 0) return;
    setUploading(true);
    try {
      let last: VideoOut | null = null;
      for (const file of files) {
        const out = await api.videos.upload(file);
        last = {
          filename: out.filename,
          size_bytes: out.size_bytes,
          modified_at: new Date().toISOString(),
          media_type: out.media_type,
          duration_sec: out.duration_sec,
        };
      }
      const list = await api.videos.list();
      setMedia(list);
      if (last) {
        selectItem(last);
        push(
          files.length === 1 ? `Загружено: ${last.filename}` : `Загружено файлов: ${files.length}`,
          "success"
        );
      }
    } catch (err) {
      push((err as Error).message, "error");
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
        when: whenIso,
      });
      push(whenIso ? "Публикация запланирована" : "Публикация добавлена в очередь", "success");
      setCaption("");
      setWhenLocal("");
      const [jobsMedia, rows] = await Promise.all([
        api.videos.list(),
        api.publications.list({ limit: 100 }),
      ]);
      setMedia(jobsMedia);
      setPublications(rows);
    } catch (err) {
      push((err as Error).message, "error");
    } finally {
      setSaving(false);
    }
  }

  async function quickPublish(item: VideoOut) {
    const account = defaultUsername || username;
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
      const list = await api.videos.list();
      setMedia(list);
      setSelectedFilename(list[0]?.filename ?? null);
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

      <Card title="Загрузка в библиотеку">
        <DropZone
          accept="video/mp4,video/quicktime,video/x-m4v,image/jpeg,image/png,image/webp"
          disabled={uploading}
          staging
          multiple
          title="Перетащите готовые Reels (.mp4)"
          hint=".mp4 / .mov — или фото .jpg / .png / .webp"
          onFile={(file) => uploadFiles([file])}
          onFiles={uploadFiles}
        />
        {uploading ? <div className="text-xs text-slate-400 mt-2">Загрузка…</div> : null}
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
            tab={libraryTab}
            search={search}
            onTabChange={setLibraryTab}
            onSearchChange={setSearch}
            onSelect={selectItem}
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
            onUsernameChange={setUsername}
            onPostTypeChange={setPostType}
            onWhenChange={setWhenLocal}
            onCaptionChange={setCaption}
            onPublish={() => enqueuePublication()}
            onDelete={deleteSelected}
          />
        </Card>
      </div>

      <Card title="Статистика опубликованных медиа" description={`${publications.length} записей`}>
        {publications.length === 0 ? (
          <div className="text-sm text-slate-500">Публикаций пока нет.</div>
        ) : (
          <div className="overflow-x-auto -mx-5">
            <table className="table-base">
              <thead>
                <tr>
                  <th>Аккаунт</th>
                  <th>Тип</th>
                  <th>Медиа</th>
                  <th>Статус</th>
                  <th>Ошибка</th>
                  <th>Просмотры / Воспроизведения</th>
                  <th>Лайки</th>
                  <th>Комментарии</th>
                  <th>Сохранения / Репосты</th>
                  <th>Последняя статистика</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {publications.map((row) => (
                  <tr key={row.id} className="hover:bg-slate-900/40">
                    <td className="font-medium">@{row.account_username ?? row.account_id}</td>
                    <td className="text-slate-300">{POST_TYPE_LABELS[row.post_type ?? "reel"] ?? row.post_type ?? "reel"}</td>
                    <td className="text-xs text-slate-400">
                      <div>{row.media_code ?? row.media_id ?? "-"}</div>
                      <div className="text-slate-500">{basename(row.final_media_path)}</div>
                    </td>
                    <td className={row.success ? "text-emerald-300" : "text-rose-300"}>
                      {row.success ? "опубликовано" : "ошибка"}
                    </td>
                    <td className="text-xs text-rose-300 max-w-[200px] break-words">
                      {row.error ?? "—"}
                    </td>
                    <td className="tabular-nums">
                      {count(row.view_count)} / {count(row.play_count)}
                    </td>
                    <td className="tabular-nums">{count(row.like_count)}</td>
                    <td className="tabular-nums">{count(row.comment_count)}</td>
                    <td className="tabular-nums">
                      {count(row.save_count)} / {count(row.share_count)}
                    </td>
                    <td className="text-xs text-slate-400">
                      {row.last_stats_at ? new Date(row.last_stats_at).toLocaleString("ru-RU") : "-"}
                    </td>
                    <td className="text-right">
                      <button
                        type="button"
                        className="btn-ghost text-xs"
                        disabled={!row.success || !row.media_id || refreshingId === row.id}
                        onClick={() => refreshStats(row)}
                      >
                        {refreshingId === row.id ? (
                          <RefreshCw size={14} className="animate-spin" />
                        ) : (
                          <BarChart3 size={14} />
                        )}
                        Обновить статистику
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
