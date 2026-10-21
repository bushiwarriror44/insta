import { BarChart3, Clapperboard, Layers, Library, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { api, formatApiError } from "../api/client";
import { Card } from "../components/Card";
import { DropZone } from "../components/DropZone";
import { EmptyState } from "../components/EmptyState";
import { Loader } from "../components/Loader";
import { MediaLibraryGrid } from "../components/MediaLibraryGrid";
import { MediaPreviewPanel } from "../components/MediaPreviewPanel";
import { PageHeader } from "../components/PageHeader";
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

function postTypeForAccount(
  account: AccountOut | null | undefined,
  item: { media_type: string } | null
): PostType {
  const platform = account?.platform || "instagram";
  if (platform === "youtube") return "youtube_short";
  if (platform === "tiktok") return "tiktok";
  if (item?.media_type === "image") return "feed_photo";
  return "reel";
}

function postTypeAllowed(account: AccountOut | null | undefined, item: { media_type: string } | null, type: PostType): boolean {
  const platform = account?.platform || "instagram";
  const media = item?.media_type;
  if (platform === "youtube") return media === "video" && type === "youtube_short";
  if (platform === "tiktok") return media === "video" && type === "tiktok";
  if (media === "image") return type === "feed_photo";
  return type === "reel" || type === "feed_video";
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
  const [searchParams, setSearchParams] = useSearchParams();
  const tabFromUrl = (() => {
    const tab = searchParams.get("tab");
    return tab === "image" || tab === "video" ? tab : "";
  })();
  const usernameFromUrl = searchParams.get("username") || "";
  const accountFromUrl = Number(searchParams.get("account") || "") || null;
  const mediaFromUrl = searchParams.get("media") || "";

  const [accounts, setAccounts] = useState<AccountOut[]>([]);
  const [media, setMedia] = useState<VideoOut[]>([]);
  const [publications, setPublications] = useState<PublicationOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [refreshingId, setRefreshingId] = useState<number | null>(null);
  const [accountId, setAccountIdState] = useState<number | null>(accountFromUrl);
  const [postType, setPostType] = useState<PostType>("reel");
  const [selectedFilename, setSelectedFilename] = useState<string | null>(mediaFromUrl || null);
  const [libraryTab, setLibraryTabState] = useState<"video" | "image">(
    tabFromUrl === "image" ? "image" : "video"
  );
  const [search, setSearch] = useState("");
  const [whenLocal, setWhenLocal] = useState("");
  const [caption, setCaption] = useState("");
  const [skipImageCompress, setSkipImageCompress] = useState(false);
  const [checkedFilenames, setCheckedFilenames] = useState<Set<string>>(() => new Set());
  const [archiveBusy, setArchiveBusy] = useState(false);
  const [downloadBusy, setDownloadBusy] = useState(false);
  const [uploadQueue, setUploadQueue] = useState<UploadQueueItem[]>([]);
  const [generatePrompt, setGeneratePrompt] = useState("");
  const [generateRef, setGenerateRef] = useState("");
  const [joinIds, setJoinIds] = useState("");
  const urlHydrated = useRef(false);

  const patchUrl = useCallback(
    (patch: { tab?: "video" | "image"; username?: string; account?: string | null; media?: string | null }) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (patch.tab !== undefined) {
            if (patch.tab === "video") next.delete("tab");
            else next.set("tab", patch.tab);
          }
          if (patch.username !== undefined) {
            if (patch.username) next.set("username", patch.username);
            else next.delete("username");
          }
          if (patch.account !== undefined) {
            if (patch.account) next.set("account", patch.account);
            else next.delete("account");
          }
          if (patch.media !== undefined) {
            if (patch.media) next.set("media", patch.media);
            else next.delete("media");
          }
          return next;
        },
        { replace: true }
      );
    },
    [setSearchParams]
  );

  const setLibraryTab = useCallback(
    (tab: "video" | "image") => {
      setLibraryTabState(tab);
      patchUrl({ tab });
    },
    [patchUrl]
  );

  const selectedItem = useMemo(
    () => media.find((m) => m.filename === selectedFilename) ?? null,
    [media, selectedFilename]
  );

  const selectedAccount = useMemo(
    () => accounts.find((a) => a.id === accountId) ?? null,
    [accounts, accountId]
  );

  const setAccountId = useCallback(
    (next: number) => {
      const row = accounts.find((a) => a.id === next);
      setAccountIdState(next);
      patchUrl({ username: row?.username ?? "", account: String(next) });
      setPostType(postTypeForAccount(row, selectedItem));
    },
    [accounts, patchUrl, selectedItem]
  );

  useEffect(() => {
    if (tabFromUrl && tabFromUrl !== libraryTab) {
      setLibraryTabState(tabFromUrl);
    }
  }, [tabFromUrl, libraryTab]);

  useEffect(() => {
    if (!accounts.length) return;
    setAccountIdState((current) => {
      if (current != null && accounts.some((a) => a.id === current)) return current;
      if (accountFromUrl != null && accounts.some((a) => a.id === accountFromUrl)) return accountFromUrl;
      if (usernameFromUrl) {
        const matches = accounts.filter((a) => a.username === usernameFromUrl);
        return matches.length === 1 ? matches[0].id : null;
      }
      return accounts.find((a) => a.status === "active")?.id ?? accounts[0]?.id ?? null;
    });
  }, [accounts, accountFromUrl, usernameFromUrl]);

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
  }, []);

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
    if (media.length === 0) return;
    const existing =
      selectedFilename != null
        ? media.find((m) => m.filename === selectedFilename)
        : undefined;
    if (existing) {
      if (!urlHydrated.current) {
        urlHydrated.current = true;
        setLibraryTabState(existing.media_type);
        setPostType(postTypeForAccount(selectedAccount, existing));
        if (!mediaFromUrl || !tabFromUrl) {
          patchUrl({
            media: existing.filename,
            tab: existing.media_type,
          });
        }
      }
      return;
    }
    const fromUrl = mediaFromUrl ? media.find((m) => m.filename === mediaFromUrl) : null;
    const firstVideo = media.find((m) => m.media_type === "video");
    const pick = fromUrl ?? firstVideo ?? media[0];
    urlHydrated.current = true;
    setSelectedFilename(pick.filename);
    setLibraryTabState(pick.media_type);
    setPostType(postTypeForAccount(selectedAccount, pick));
    patchUrl({ media: pick.filename, tab: pick.media_type });
  }, [media, selectedFilename, mediaFromUrl, tabFromUrl, patchUrl, selectedAccount]);

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

  useEffect(() => {
    if (!selectedAccount || !selectedItem) return;
    setPostType((current) =>
      postTypeAllowed(selectedAccount, selectedItem, current)
        ? current
        : postTypeForAccount(selectedAccount, selectedItem)
    );
  }, [selectedAccount, selectedItem]);

  function selectItem(item: VideoOut) {
    setSelectedFilename(item.filename);
    setLibraryTabState(item.media_type);
    setPostType(postTypeForAccount(selectedAccount, item));
    patchUrl({ media: item.filename, tab: item.media_type });
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
    accountIdOverride?: number;
    captionOverride?: string | null;
    whenOverride?: string | null;
    title?: string;
    description?: string;
    tags?: string;
  }) {
    const mediaFilename = opts?.mediaFilename ?? selectedFilename;
    const id = opts?.accountIdOverride ?? accountId;
    const account = accounts.find((row) => row.id === id) ?? null;
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
      const created = await api.jobs.enqueue({
        username: account.username,
        account_id: account.id,
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
        href: created?.id ? `/activity?job=${created.id}` : "/activity",
      });
      setCaption("");
      setWhenLocal("");
      await reload();
    } catch (err) {
      push(formatApiError(err), "error");
    } finally {
      setSaving(false);
    }
  }

  async function quickPublish(item: VideoOut) {
    const account = selectedAccount ?? accounts.find((row) => row.status === "active") ?? accounts[0];
    if (!account) {
      push("Сначала добавьте аккаунт", "error");
      return;
    }
    selectItem(item);
    await enqueuePublication({
      mediaFilename: item.filename,
      postTypeOverride: postTypeForAccount(account, item),
      accountIdOverride: account.id,
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
      <PageHeader
        icon={Library}
        title="Библиотека"
        description="Загружайте готовые Reels, просматривайте в браузере и публикуйте в один клик."
      />
      <Card>
        <h2 className="font-medium">Сгенерировать / склеить</h2>
        <div className="flex flex-wrap gap-2">
          <input className="input min-w-[12rem] flex-1" placeholder="Промпт для рендера" value={generatePrompt} onChange={(e) => setGeneratePrompt(e.target.value)} />
          <select
            className="input w-48"
            aria-label="референс"
            value={generateRef}
            onChange={(e) => setGenerateRef(e.target.value)}
          >
            <option value="">без референса</option>
            {media
              .filter((m) => m.media_type === "image" || m.media_type === "video")
              .map((m) => (
                <option key={m.filename} value={m.filename}>
                  {m.filename}
                </option>
              ))}
          </select>
          <button
            className="btn-primary shrink-0"
            disabled={!generatePrompt.trim()}
            onClick={async () => {
              try {
                const ref = generateRef.trim();
                const item = media.find((m) => m.filename === ref);
                const role = item?.media_type === "video" ? "motion_video" : "start_image";
                const created = await api.factory.createGeneration({
                  prompt: generatePrompt.trim(),
                  backend: ref && item?.media_type === "image" ? "auto" : "auto",
                  reference_filename: ref || undefined,
                  reference_role: ref ? role : undefined,
                });
                setGeneratePrompt("");
                setGenerateRef("");
                push("Рендер в очереди", "success", {
                  label: "Открыть",
                  href: created?.id ? `/renders?gen=${created.id}` : "/renders",
                });
              } catch (err) {
                push(formatApiError(err), "error");
              }
            }}
          >
            <Clapperboard className="h-4 w-4" />
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
                const created = await api.factory.createComposition({ clip_ids });
                setJoinIds("");
                push("Склейка в очереди", "success", {
                  label: "Открыть",
                  href: created?.id ? `/renders?join=${created.id}` : "/renders",
                });
              } catch (err) {
                push(formatApiError(err), "error");
              }
            }}
          >
            <Layers className="h-4 w-4" />
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
            accountId={accountId}
            postType={postType}
            whenLocal={whenLocal}
            caption={caption}
            saving={saving}
            downloadBusy={downloadBusy}
            onAccountChange={setAccountId}
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
          <EmptyState>Публикаций пока нет.</EmptyState>
        ) : (
          <div className="table-scroll">
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
                <th className="hidden sm:table-cell">Тип</th>
                <th className="hidden md:table-cell">Медиа</th>
                <th>Статус</th>
                <th className="hidden lg:table-cell">Ошибка</th>
                <th className="hidden md:table-cell">Статистика</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {publications.map((row) => (
                <tr key={row.id} className="hover:bg-slate-900/40">
                  <td className="truncate font-medium" title={`@${row.account_username ?? row.account_id}`}>
                    @{row.account_username ?? row.account_id}
                  </td>
                  <td className="hidden truncate text-slate-300 sm:table-cell">
                    {POST_TYPE_LABELS[row.post_type ?? "reel"] ?? row.post_type ?? "reel"}
                  </td>
                  <td className="hidden min-w-0 text-[11px] text-slate-400 md:table-cell">
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
                  <td className="hidden truncate text-[11px] text-rose-300 lg:table-cell" title={row.error ?? "—"}>
                    {row.error ?? "—"}
                  </td>
                  <td className="hidden tabular-nums text-[11px] text-slate-300 md:table-cell">
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
          </div>
        )}
      </Card>
    </div>
  );
}
