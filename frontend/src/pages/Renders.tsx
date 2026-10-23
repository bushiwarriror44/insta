import { Ban, Clapperboard, Layers, Play, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import clsx from "clsx";
import { useSearchParams } from "react-router-dom";

import { api, formatApiError } from "../api/client";
import { Card } from "../components/Card";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { useToast } from "../context/ToastContext";
import { usePollWhenVisible } from "../hooks/usePollWhenVisible";
import { useAssistantMutate } from "../lib/assistantMutate";
import { withLocalRenderHint } from "../lib/renderErrors";
import { retryGenerationOnLocal } from "../lib/pollGeneration";
import { RenderLocalSwitchModal, type LocalSwitchOffer } from "../components/RenderLocalSwitchModal";
import {
  GenerationStagePulse,
  generationStageLabel,
  isTerminalGeneration,
} from "../components/RenderProgressCard";
import { RenderReferenceField } from "../components/RenderReferenceField";
import {
  clipboardMediaFiles,
  mergeReferences,
  modeAfterReferences,
  uploadRenderReference,
  type RenderInputMode,
  type RenderReference,
} from "../lib/referenceUpload";
import type { AccountOut, MediaAssetOut, RenderBackendOut } from "../api/types";

type JoinSlot = { key: string; assetId: string; cutaway: boolean };

function joinSlotLabel(row: JoinSlot, rows: JoinSlot[]) {
  if (row.cutaway) {
    const cutaways = rows.filter((item) => item.cutaway);
    const number = cutaways.findIndex((item) => item.key === row.key) + 1;
    return cutaways.length > 1 ? `Перебивка ${number}` : "Перебивка";
  }
  const mains = rows.filter((item) => !item.cutaway);
  const which = mains.findIndex((item) => item.key === row.key);
  return which <= 0 ? "Ролик 1" : "Ролик 2";
}

type Gen = {
  id: number;
  status: string;
  prompt: string;
  stage: string;
  post_title: string;
  last_error: string | null;
  cost_usd: number;
  backend?: string;
  queue_position?: number | null;
  offer_local_switch?: boolean;
};
const LOCAL_OFFER_DISMISS_KEY = "renders:local-offer-dismissed";
type Join = { id: number; status: string; post_title: string; last_error: string | null; clips: number };

const FRAME_SIZES = [
  { id: "9:16-720", label: "9:16 · 720×1280", width: 720, height: 1280 },
  { id: "9:16-1080", label: "9:16 · 1080×1920", width: 1080, height: 1920 },
  { id: "4:5", label: "4:5 · 1080×1350", width: 1080, height: 1350 },
  { id: "1:1", label: "1:1 · 1080×1080", width: 1080, height: 1080 },
  { id: "16:9", label: "16:9 · 1280×720", width: 1280, height: 720 },
] as const;

const LOCAL_DURATIONS = [5, 10] as const;
const CLOUD_DURATIONS = [5, 10, 15, 30] as const;
type DurationS = (typeof CLOUD_DURATIONS)[number];

const DEFAULT_NEGATIVE_PROMPT =
  "текст, субтитры, водяной знак, логотип, UI, рамка, лишние руки, лишние пальцы, деформированные конечности, искажённое лицо, мутный кадр, низкое качество, артефакты, двоение, морфинг, тряска камеры, стоп-кадр, чёрные полосы, blurry, watermark, bad anatomy";

const DEFAULT_POSITIVE_PROMPT =
  "проработай мелкие детали, чёткие текстуры, плавная непрерывная анимация, естественное движение, стабильная камера";

const PLATFORMS = [
  { id: "", label: "без платформы", duration: null },
  { id: "reels", label: "Reels", duration: 15 },
  { id: "shorts", label: "Shorts", duration: 30 },
  { id: "tiktok", label: "TikTok", duration: 15 },
] as const;

function shortDurationOnly(backend: string, inputMode: RenderInputMode): boolean {
  return backend === "local" || inputMode === "image_slideshow";
}

function backendLabel(name: string) {
  return name === "auto" ? "Авто" : name;
}

function referenceMismatch(references: RenderReference[], inputMode: RenderInputMode): string | null {
  if (!references.length) return null;
  const hasVideo = references.some((item) => item.mediaType === "video");
  const hasImage = references.some((item) => item.mediaType === "image");
  if (inputMode === "image_slideshow" && hasVideo) {
    return "Ken Burns работает только с фото. Выберите изображение или режим «По видео».";
  }
  if (inputMode === "video_to_video" && !hasVideo) {
    return "Режим «По видео» нужен короткий ролик. Для картинки выберите «По фото».";
  }
  if (inputMode === "image_to_video" && !hasImage) {
    return "Режим «По фото» нужен кадр-картинку. Для ролика выберите «По видео».";
  }
  return null;
}

function referenceBackendNote(
  backends: RenderBackendOut[],
  backend: string,
  references: RenderReference[],
  inputMode: RenderInputMode
): string | null {
  const reference = references[0];
  if (!reference || (backend !== "local" && backend !== "auto")) return null;
  const engine = backends.find((item) => item.name === backend);
  if (!engine) return null;
  if (inputMode === "image_to_video" && engine.supports_i2v === false) {
    return "Выбранный движок не принимает фото как референс. «Авто» пропустит неподходящие движки в цепочке.";
  }
  if (inputMode === "video_to_video" && engine.supports_v2v === false) {
    return "Выбранный движок не принимает видео-референс. «Авто» пропустит неподходящие движки в цепочке.";
  }
  return null;
}

export function Renders() {
  const { push } = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const genFromUrl = Number(searchParams.get("gen") || 0) || null;
  const joinFromUrl = Number(searchParams.get("join") || 0) || null;
  const [gens, setGens] = useState<Gen[]>([]);
  const [joins, setJoins] = useState<Join[]>([]);
  const [accounts, setAccounts] = useState<AccountOut[]>([]);
  const [backends, setBackends] = useState<RenderBackendOut[]>([]);
  const [prompt, setPrompt] = useState("");
  const [backend, setBackend] = useState("local");
  const [accountId, setAccountId] = useState<number | "">("");
  const [frameId, setFrameId] = useState<(typeof FRAME_SIZES)[number]["id"]>("9:16-720");
  const [durationS, setDurationS] = useState<DurationS>(5);
  const [negativePrompt, setNegativePrompt] = useState(DEFAULT_NEGATIVE_PROMPT);
  const [positivePrompt, setPositivePrompt] = useState(DEFAULT_POSITIVE_PROMPT);
  const [addSound, setAddSound] = useState(true);
  const [soundtrack, setSoundtrack] = useState("");
  const [uploadingAudio, setUploadingAudio] = useState(false);
  const [audioDragging, setAudioDragging] = useState(false);
  const audioInputRef = useRef<HTMLInputElement>(null);
  const [seed, setSeed] = useState("");
  const [platform, setPlatform] = useState<(typeof PLATFORMS)[number]["id"]>("");
  const [joinRows, setJoinRows] = useState<JoinSlot[]>([
    { key: "main-1", assetId: "", cutaway: false },
    { key: "main-2", assetId: "", cutaway: false },
  ]);
  const joinKey = useRef(2);
  const [joinAudio, setJoinAudio] = useState("");
  const [joinAudioStart, setJoinAudioStart] = useState("0");
  const [videoAssets, setVideoAssets] = useState<MediaAssetOut[]>([]);
  const [audioAssets, setAudioAssets] = useState<MediaAssetOut[]>([]);
  const [libraryFiles, setLibraryFiles] = useState<Array<{ filename: string; media_type: string }>>([]);
  const [references, setReferences] = useState<RenderReference[]>([]);
  const [inputMode, setInputMode] = useState<RenderInputMode>("");
  const [uploadingReference, setUploadingReference] = useState(false);
  const [localOffer, setLocalOffer] = useState<LocalSwitchOffer | null>(null);
  const [localOfferBusy, setLocalOfferBusy] = useState(false);
  const highlightRef = useRef<HTMLTableRowElement | null>(null);

  const durations = shortDurationOnly(backend, inputMode) ? LOCAL_DURATIONS : CLOUD_DURATIONS;

  useEffect(() => {
    if (shortDurationOnly(backend, inputMode) && durationS > 10) setDurationS(10);
  }, [backend, inputMode, durationS]);

  useEffect(() => {
    if (!genFromUrl && !joinFromUrl) return;
    const node = highlightRef.current;
    if (node && typeof node.scrollIntoView === "function") {
      node.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }, [genFromUrl, joinFromUrl, gens, joins]);

  const reload = useCallback(async () => {
    const [g, c, accs, engines, uploads, videos, audios] = await Promise.all([
      api.factory.generations(),
      api.factory.compositions(),
      api.accounts.list(),
      api.factory.backends(),
      api.videos.list().catch(() => []),
      api.factory.assets({ kind: "video", limit: 100 }).catch(() => []),
      api.factory.assets({ kind: "audio", limit: 100 }).catch(() => []),
    ]);
    setGens(g);
    setJoins(c);
    setAccounts(accs);
    setBackends(engines);
    setVideoAssets(videos);
    setAudioAssets(audios);
    setLibraryFiles(
      uploads.map((f) => ({ filename: f.filename, media_type: f.media_type ?? "video" }))
    );
  }, []);

  const runAction = useCallback(
    async (fn: () => Promise<unknown>) => {
      try {
        await fn();
        await reload();
      } catch (err) {
        push(withLocalRenderHint(formatApiError(err)), "error");
      }
    },
    [push, reload]
  );

  useAssistantMutate(() => reload().catch(() => undefined));

  const poll = useCallback(
    () => reload().catch((err) => push(formatApiError(err), "error")),
    [push, reload]
  );
  usePollWhenVisible(poll, 8000);

  useEffect(() => {
    if (localOffer || localOfferBusy) return;
    let dismissed: number[] = [];
    try {
      dismissed = JSON.parse(sessionStorage.getItem(LOCAL_OFFER_DISMISS_KEY) || "[]") as number[];
    } catch {
      dismissed = [];
    }
    const dismissedSet = new Set(dismissed);
    const row = gens.find((g) => g.offer_local_switch && !dismissedSet.has(g.id));
    if (row) {
      setLocalOffer({
        job_id: row.id,
        message:
          "Облачные бэкенды не справились. Сейчас сработает переключение на локальный Wan (Salad / WAN_BASE_URL).",
      });
    }
  }, [gens, localOffer, localOfferBusy]);

  const dismissLocalOffer = (jobId: number) => {
    try {
      const prev = JSON.parse(sessionStorage.getItem(LOCAL_OFFER_DISMISS_KEY) || "[]") as number[];
      if (!prev.includes(jobId)) {
        sessionStorage.setItem(LOCAL_OFFER_DISMISS_KEY, JSON.stringify([...prev, jobId]));
      }
    } catch {
      sessionStorage.setItem(LOCAL_OFFER_DISMISS_KEY, JSON.stringify([jobId]));
    }
  };

  const acceptAudio = (file: File) => {
    const suffix = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
    if (![".mp3", ".m4a", ".wav", ".aac", ".ogg"].includes(suffix)) {
      push("Нужен файл mp3, m4a, wav, aac или ogg", "error");
      return;
    }
    setUploadingAudio(true);
    void api.videos
      .upload(file, { compress: false })
      .then((out) => {
        setSoundtrack(out.filename);
        setLibraryFiles((prev) =>
          prev.some((item) => item.filename === out.filename)
            ? prev
            : [...prev, { filename: out.filename, media_type: "audio" }]
        );
      })
      .catch((err) => push(formatApiError(err), "error"))
      .finally(() => setUploadingAudio(false));
  };

  const queueRender = async () => {
    if (!prompt.trim() || uploadingReference || uploadingAudio) return;
    const mismatch = referenceMismatch(references, inputMode);
    if (mismatch) {
      push(mismatch, "error");
      return;
    }
    try {
      const names = references.map((item) => item.filename);
      const role = references.some((item) => item.mediaType === "video")
        ? "motion_video"
        : "start_image";
      const frame = FRAME_SIZES.find((size) => size.id === frameId) ?? FRAME_SIZES[0];
      const seedNumber = seed.trim() ? Number(seed) : undefined;
      const scene = prompt.trim();
      const extra = positivePrompt.trim();
      const created = await api.factory.createGeneration({
        prompt: extra ? `${scene}. ${extra}` : scene,
        backend: inputMode === "image_slideshow" ? "slideshow" : backend,
        audio_mode: !addSound ? "none" : soundtrack ? "library" : "generate",
        ...(addSound && soundtrack ? { audio_filename: soundtrack } : {}),
        account_id: typeof accountId === "number" ? accountId : undefined,
        width: frame.width,
        height: frame.height,
        duration_s: durationS,
        ...(negativePrompt.trim() ? { negative_prompt: negativePrompt.trim() } : {}),
        ...(seedNumber !== undefined ? { seed: seedNumber } : {}),
        ...(names.length
          ? {
              input_mode: inputMode || undefined,
              reference_filenames: names,
              reference_filename: names[0],
              reference_role: role,
            }
          : {}),
      });
      setPrompt("");
      setReferences([]);
      setInputMode("");
      const href = created?.id ? `/renders?gen=${created.id}` : "/renders";
      push("Рендер в очереди", "success", { label: "Открыть", href });
      if (created?.id) {
        setSearchParams(
          (prev) => {
            const next = new URLSearchParams(prev);
            next.set("gen", String(created.id));
            next.delete("join");
            return next;
          },
          { replace: true }
        );
      }
      await reload();
    } catch (err) {
      push(withLocalRenderHint(formatApiError(err)), "error");
    }
  };

  const insertCutaway = () => {
    joinKey.current += 1;
    const key = `cut-${joinKey.current}`;
    setJoinRows((rows) => {
      const next = [...rows];
      next.splice(Math.max(rows.length - 1, 1), 0, { key, assetId: "", cutaway: true });
      return next;
    });
  };

  const moveJoinRow = (index: number, direction: -1 | 1) => {
    setJoinRows((rows) => {
      const target = index + direction;
      if (target < 0 || target >= rows.length) return rows;
      const next = [...rows];
      const [item] = next.splice(index, 1);
      next.splice(target, 0, item);
      return next;
    });
  };

  const removeJoinRow = (index: number) => {
    setJoinRows((rows) => (rows.length <= 2 ? rows : rows.filter((_, i) => i !== index)));
  };

  const queueJoin = async () => {
    const clip_ids = joinRows.map((row) => Number(row.assetId)).filter((id) => id > 0);
    if (clip_ids.length < 2 || joinRows.some((row) => !row.assetId)) {
      push("Нужны два ролика", "error");
      return;
    }
    const start = Number(joinAudioStart);
    const audio_start_s = Number.isFinite(start) && start > 0 ? start : 0;
    const body: {
      clip_ids: number[];
      audio_start_s: number;
      account_id?: number;
      audio_asset_id?: number;
      audio_filename?: string;
    } = {
      clip_ids,
      audio_start_s,
      account_id: typeof accountId === "number" ? accountId : undefined,
    };
    if (joinAudio.startsWith("asset:")) body.audio_asset_id = Number(joinAudio.slice(6));
    if (joinAudio.startsWith("file:")) body.audio_filename = joinAudio.slice(5);
    try {
      const created = await api.factory.createComposition(body);
      setJoinRows([
        { key: "main-1", assetId: "", cutaway: false },
        { key: "main-2", assetId: "", cutaway: false },
      ]);
      setJoinAudio("");
      setJoinAudioStart("0");
      const href = created?.id ? `/renders?join=${created.id}` : "/renders";
      push("Склейка в очереди", "success", { label: "Открыть", href });
      if (created?.id) {
        setSearchParams(
          (prev) => {
            const next = new URLSearchParams(prev);
            next.set("join", String(created.id));
            next.delete("gen");
            return next;
          },
          { replace: true }
        );
      }
      await reload();
    } catch (err) {
      push(formatApiError(err), "error");
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader icon={Clapperboard} title="Рендеры и склейки" />
      <Card className="!overflow-visible">
        <div className="space-y-1">
          <h2 className="font-medium">Новый рендер</h2>
          <p className="text-sm text-slate-400">
            Опишите ролик. При желании приложите пример кадра или короткое видео — генерация
            возьмёт его за основу.
          </p>
        </div>
        {backends.length ? (
          <div className="space-y-2">
            <div className="text-sm text-slate-200">Движок</div>
            <div className="flex flex-wrap gap-2">
              {backends.map((engine) => (
                <button
                  key={engine.name}
                  type="button"
                  title={engine.detail || engine.licence}
                  aria-pressed={backend === engine.name}
                  onClick={() => setBackend(engine.name)}
                  className={clsx(
                    "rounded-full px-2.5 py-1 text-xs ring-1 transition-colors",
                    backend === engine.name
                      ? "bg-brand-600/20 text-brand-200 ring-brand-500/40"
                      : engine.healthy
                        ? "text-emerald-400 ring-emerald-500/30 hover:bg-emerald-500/10"
                        : "text-slate-500 ring-slate-700 hover:bg-slate-800/60"
                  )}
                >
                  {backendLabel(engine.name)}
                  {engine.experimental ? " · exp" : ""}
                  {engine.healthy ? " · ок" : " · нет"}
                </button>
              ))}
            </div>
          </div>
        ) : null}
        <label className="block text-sm text-slate-200">
          Описание видео
          <textarea
            className="input mt-1 min-h-[96px]"
            placeholder="Промпт"
            aria-label="Описание видео"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
                event.preventDefault();
                void queueRender();
              }
            }}
            onPaste={(event) => {
              const files = clipboardMediaFiles(event.nativeEvent);
              if (!files.length) return;
              event.preventDefault();
              setUploadingReference(true);
              void (async () => {
                const uploaded: RenderReference[] = [];
                for (const file of files) {
                  uploaded.push(await uploadRenderReference(file));
                }
                setReferences((current) => {
                  const next = mergeReferences(current, uploaded);
                  setInputMode((mode) => modeAfterReferences(mode, next));
                  return next;
                });
                setLibraryFiles((prev) => {
                  const known = new Set(prev.map((item) => item.filename));
                  const extra = uploaded
                    .filter((item) => !known.has(item.filename))
                    .map((item) => ({ filename: item.filename, media_type: item.mediaType }));
                  return extra.length ? [...prev, ...extra] : prev;
                });
              })()
                .catch((err) => push(formatApiError(err), "error"))
                .finally(() => setUploadingReference(false));
            }}
          />
          <span className="mt-1 block text-xs text-slate-500">
            Ctrl+V — вставить одно или несколько фото как референс
          </span>
        </label>
        <RenderReferenceField
          value={references}
          libraryFiles={libraryFiles}
          inputMode={inputMode}
          disabled={uploadingReference}
          backendNote={referenceBackendNote(backends, backend, references, inputMode)}
          onChange={(next) => {
            setReferences(next);
            setLibraryFiles((prev) => {
              const known = new Set(prev.map((item) => item.filename));
              const extra = next
                .filter((item) => !known.has(item.filename))
                .map((item) => ({ filename: item.filename, media_type: item.mediaType }));
              return extra.length ? [...prev, ...extra] : prev;
            });
          }}
          onInputModeChange={setInputMode}
        />
        <div className="space-y-2">
          <div className="text-sm text-slate-200">Кадр</div>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <label className="block text-sm text-slate-200">
            Платформа
            <select
              className="input mt-1"
              aria-label="Платформа"
              value={platform}
              onChange={(e) => {
                const next = e.target.value as (typeof PLATFORMS)[number]["id"];
                setPlatform(next);
                const preset = PLATFORMS.find((item) => item.id === next);
                if (!preset?.duration) return;
                setFrameId("9:16-1080");
                const cap = shortDurationOnly(backend, inputMode) ? 10 : preset.duration;
                setDurationS(cap as DurationS);
              }}
            >
              {PLATFORMS.map((item) => (
                <option key={item.id || "none"} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm text-slate-200">
            Размер кадра
            <select
              className="input mt-1"
              aria-label="Размер кадра"
              value={frameId}
              onChange={(e) => setFrameId(e.target.value as (typeof FRAME_SIZES)[number]["id"])}
            >
              {FRAME_SIZES.map((size) => (
                <option key={size.id} value={size.id}>
                  {size.label}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm text-slate-200">
            Длительность
            <select
              className="input mt-1"
              aria-label="Длительность"
              value={durationS}
              onChange={(e) => setDurationS(Number(e.target.value) as DurationS)}
            >
              {durations.map((seconds) => (
                <option key={seconds} value={seconds}>
                  {seconds} с
                </option>
              ))}
            </select>
          </label>
          </div>
        </div>
        <div className="space-y-2">
          <label className="flex items-center gap-2 text-sm text-slate-200">
            <input
              type="checkbox"
              aria-label="Добавить звук"
              checked={addSound}
              onChange={(e) => setAddSound(e.target.checked)}
            />
            Добавить звук
          </label>
          {addSound ? (
            <div className="space-y-3 rounded-xl border border-slate-800 p-3">
              <div
                onDragOver={(event) => {
                  event.preventDefault();
                  if (!uploadingAudio) setAudioDragging(true);
                }}
                onDragLeave={() => setAudioDragging(false)}
                onDrop={(event) => {
                  event.preventDefault();
                  setAudioDragging(false);
                  const file = event.dataTransfer.files?.[0];
                  if (file) acceptAudio(file);
                }}
                className={clsx(
                  "flex flex-col items-center gap-2 rounded-xl border border-dashed border-slate-700 bg-slate-900/40 px-4 py-5 text-center",
                  audioDragging && "border-brand-500 bg-brand-500/10",
                  uploadingAudio && "opacity-60"
                )}
              >
                <p className="text-sm text-slate-300">
                  {uploadingAudio ? "Загрузка дорожки…" : "Перетащите свою дорожку"}
                </p>
                <button
                  type="button"
                  className="btn-ghost btn-compact min-h-[44px]"
                  disabled={uploadingAudio}
                  onClick={() => audioInputRef.current?.click()}
                >
                  Выбрать файл
                </button>
                <input
                  ref={audioInputRef}
                  type="file"
                  accept=".mp3,.m4a,.wav,.aac,.ogg,audio/*"
                  className="hidden"
                  aria-label="Своя дорожка"
                  disabled={uploadingAudio}
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    event.target.value = "";
                    if (file) acceptAudio(file);
                  }}
                />
              </div>
              {soundtrack ? (
                <p className="flex items-center gap-2 text-sm text-slate-300">
                  <span className="min-w-0 truncate">{soundtrack}</span>
                  <button
                    type="button"
                    className="btn-ghost btn-compact min-h-[44px] shrink-0"
                    onClick={() => setSoundtrack("")}
                  >
                    убрать
                  </button>
                </p>
              ) : (
                <p className="text-xs text-slate-500">Без файла сгенерируется короткая дорожка.</p>
              )}
              <label className="block text-sm text-slate-400">
                или из библиотеки
                <select
                  className="input mt-1"
                  aria-label="Дорожка из библиотеки"
                  value={soundtrack}
                  onChange={(e) => setSoundtrack(e.target.value)}
                >
                  <option value="">сгенерировать дорожку</option>
                  {libraryFiles
                    .filter((file) => file.media_type === "audio")
                    .map((file) => (
                      <option key={file.filename} value={file.filename}>
                        {file.filename}
                      </option>
                    ))}
                </select>
              </label>
            </div>
          ) : null}
        </div>
        <details className="rounded-xl border border-slate-800 px-3 py-2">
          <summary className="cursor-pointer text-sm text-slate-200">Дополнительно</summary>
          <div className="mt-3 space-y-3">
            <label className="block text-sm text-slate-200">
              Позитивный промпт
              <textarea
                className="input mt-1 min-h-[72px]"
                aria-label="Позитивный промпт"
                placeholder={DEFAULT_POSITIVE_PROMPT}
                value={positivePrompt}
                onChange={(e) => setPositivePrompt(e.target.value)}
              />
            </label>
            <label className="block text-sm text-slate-200">
              Негативный промпт
              <textarea
                className="input mt-1 min-h-[72px]"
                aria-label="Негативный промпт"
                placeholder={DEFAULT_NEGATIVE_PROMPT}
                value={negativePrompt}
                onChange={(e) => setNegativePrompt(e.target.value)}
              />
            </label>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <label className="block text-sm text-slate-200">
                Seed
                <input
                  className="input mt-1"
                  aria-label="Seed"
                  inputMode="numeric"
                  placeholder="пусто — каждый раз новый"
                  value={seed}
                  onChange={(e) => setSeed(e.target.value.replace(/[^\d]/g, ""))}
                />
              </label>
              <label className="block text-sm text-slate-200">
                Аккаунт (необязательно)
                <select
                  className="input mt-1"
                  aria-label="аккаунт"
                  value={accountId}
                  onChange={(e) => setAccountId(e.target.value ? Number(e.target.value) : "")}
                >
                  <option value="">без аккаунта</option>
                  {accounts.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.username}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </div>
        </details>
        <p className="text-xs text-slate-500">
          {shortDurationOnly(backend, inputMode)
            ? "Local Wan длиннее 10 с не снимет. 480p: портрет 480×832, альбом 832×480."
            : backend === "fal"
              ? "fal снимет 5 или 10 с, ближайшее к выбранному."
              : "Локальный Wan 1.3B снимает 480p и только 5 или 10 с. Размер выше задаёт ориентацию."}
          {platform ? " 9:16, звук и поля под кнопки платформы. Файл остаётся mp4." : ""}
        </p>
        <div className="sticky bottom-0 z-10 -mx-5 -mb-5 border-t border-slate-800 bg-slate-950/95 px-5 py-3 backdrop-blur sm:static sm:mx-0 sm:mb-0 sm:border-0 sm:bg-transparent sm:p-0 sm:backdrop-blur-none">
          <button
            className="btn-primary w-full sm:w-auto"
            disabled={!prompt.trim() || uploadingReference || uploadingAudio}
            onClick={() => void queueRender()}
          >
            <Play className="h-4 w-4" />
            Поставить рендер
          </button>
        </div>
      </Card>
      <Card>
        <h2 className="font-medium mb-3">Рендеры</h2>
        <div className="table-scroll">
        <table className="table-base">
          <thead>
            <tr>
              <th>ID</th>
              <th>Статус</th>
              <th className="hidden md:table-cell">Бэкенд</th>
              <th>Заголовок</th>
              <th>Стадия</th>
              <th className="hidden lg:table-cell">Ошибка</th>
              <th className="hidden md:table-cell">$</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {gens.length === 0 ? (
              <tr>
                <td colSpan={8}>
                  <EmptyState>пока пусто</EmptyState>
                </td>
              </tr>
            ) : null}
            {gens.map((g) => (
              <tr
                key={g.id}
                ref={genFromUrl === g.id ? highlightRef : undefined}
                className={clsx(genFromUrl === g.id && "bg-brand-600/10 ring-1 ring-inset ring-brand-500/30")}
              >
                <td className="tabular-nums">{g.id}</td>
                <td>
                  <StatusBadge value={g.status} />
                </td>
                <td className="hidden md:table-cell">{g.backend || "—"}</td>
                <td className="truncate" title={g.post_title || g.prompt}>
                  {g.post_title || g.prompt.slice(0, 60)}
                </td>
                <td className="min-w-[7rem] md:min-w-[8rem]">
                  <p className="truncate text-xs text-slate-300" title={generationStageLabel(g.status, g.stage, g.queue_position)}>
                    {generationStageLabel(g.status, g.stage, g.queue_position)}
                  </p>
                  {!isTerminalGeneration(g.status) ? <GenerationStagePulse /> : null}
                </td>
                <td
                  className={clsx(
                    "hidden max-w-[200px] truncate text-xs lg:table-cell",
                    ["failed", "dead"].includes(g.status) && g.last_error ? "text-rose-300" : "text-slate-500"
                  )}
                  title={["failed", "dead"].includes(g.status) ? g.last_error || undefined : undefined}
                >
                  {["failed", "dead"].includes(g.status) ? g.last_error || "—" : "—"}
                </td>
                <td className="hidden tabular-nums md:table-cell">{g.cost_usd}</td>
                <td className="text-right">
                  <div className="flex justify-end gap-1 flex-wrap">
                    {["queued", "failed", "dead"].includes(g.status) ? (
                      <button
                        className="btn-ghost btn-compact"
                        aria-label="Отменить"
                        onClick={() => void runAction(() => api.factory.cancelGeneration(g.id))}
                      >
                        <Ban className="h-4 w-4" />
                        Отменить
                      </button>
                    ) : null}
                    {["failed", "dead", "cancelled"].includes(g.status) ? (
                      <button
                        className="btn-ghost btn-compact"
                        onClick={() => void runAction(() => api.factory.retryGeneration(g.id))}
                      >
                        <RefreshCw className="h-4 w-4" />
                        Повторить
                      </button>
                    ) : null}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </Card>
      <Card>
        <h2 className="font-medium">Склейки</h2>
        <div className="space-y-3">
          {joinRows.map((row, index) => {
            const label = joinSlotLabel(row, joinRows);
            return (
              <div key={row.key} className="flex flex-wrap items-end gap-2">
                <label className="min-w-[12rem] flex-1 text-sm">
                  {label}
                  <select
                    className="input mt-1"
                    aria-label={label}
                    value={row.assetId}
                    onChange={(event) => {
                      const value = event.target.value;
                      setJoinRows((rows) =>
                        rows.map((item) => (item.key === row.key ? { ...item, assetId: value } : item))
                      );
                    }}
                  >
                    <option value="">выберите ролик</option>
                    {videoAssets.map((asset) => (
                      <option key={asset.id} value={String(asset.id)}>
                        {(asset.prompt || "").trim() || asset.filename}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="flex gap-1">
                  <button
                    type="button"
                    className="btn-ghost btn-compact"
                    aria-label={`Поднять ${label}`}
                    disabled={index === 0}
                    onClick={() => moveJoinRow(index, -1)}
                  >
                    Вверх
                  </button>
                  <button
                    type="button"
                    className="btn-ghost btn-compact"
                    aria-label={`Опустить ${label}`}
                    disabled={index === joinRows.length - 1}
                    onClick={() => moveJoinRow(index, 1)}
                  >
                    Вниз
                  </button>
                  <button
                    type="button"
                    className="btn-ghost btn-compact"
                    aria-label={`Убрать ${label}`}
                    disabled={joinRows.length <= 2}
                    onClick={() => removeJoinRow(index)}
                  >
                    Убрать
                  </button>
                </div>
              </div>
            );
          })}
          <button type="button" className="btn-ghost" onClick={insertCutaway}>
            Вставить перебивку
          </button>
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="text-sm">
              Звук
              <select
                className="input mt-1"
                aria-label="Звук склейки"
                value={joinAudio}
                onChange={(event) => setJoinAudio(event.target.value)}
              >
                <option value="">без звука</option>
                {audioAssets.map((asset) => (
                  <option key={`asset-${asset.id}`} value={`asset:${asset.id}`}>
                    {(asset.prompt || "").trim() || asset.filename}
                  </option>
                ))}
                {libraryFiles
                  .filter((file) => file.media_type === "audio")
                  .map((file) => (
                    <option key={`file-${file.filename}`} value={`file:${file.filename}`}>
                      {file.filename}
                    </option>
                  ))}
              </select>
            </label>
            <label className="text-sm">
              Начать с секунды
              <input
                className="input mt-1"
                aria-label="Начать с секунды"
                inputMode="decimal"
                value={joinAudioStart}
                onChange={(event) => setJoinAudioStart(event.target.value.replace(/[^\d.]/g, ""))}
              />
            </label>
          </div>
          <button type="button" className="btn-ghost" onClick={() => void queueJoin()}>
            <Layers className="h-4 w-4" />
            Склеить
          </button>
        </div>
        <div className="table-scroll">
        <table className="table-base">
          <thead>
            <tr>
              <th>ID</th>
              <th>Статус</th>
              <th>Пост</th>
              <th className="hidden sm:table-cell">Клипов</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {joins.length === 0 ? (
              <tr>
                <td colSpan={5}>
                  <EmptyState>пока пусто</EmptyState>
                </td>
              </tr>
            ) : null}
            {joins.map((j) => (
              <tr
                key={j.id}
                ref={joinFromUrl === j.id ? highlightRef : undefined}
                className={clsx(joinFromUrl === j.id && "bg-brand-600/10 ring-1 ring-inset ring-brand-500/30")}
              >
                <td className="tabular-nums">{j.id}</td>
                <td>
                  <StatusBadge value={j.status} />
                </td>
                <td className="truncate" title={j.post_title}>
                  {j.post_title}
                </td>
                <td className="hidden tabular-nums sm:table-cell">{j.clips}</td>
                <td className="text-right">
                  <div className="flex justify-end gap-1 flex-wrap">
                    {["queued", "failed", "dead"].includes(j.status) ? (
                      <button
                        className="btn-ghost btn-compact"
                        aria-label="Отменить"
                        onClick={() => void runAction(() => api.factory.cancelComposition(j.id))}
                      >
                        <Ban className="h-4 w-4" />
                        Отменить
                      </button>
                    ) : null}
                    {["failed", "dead", "cancelled"].includes(j.status) ? (
                      <button
                        className="btn-ghost btn-compact"
                        onClick={() => void runAction(() => api.factory.retryComposition(j.id))}
                      >
                        <RefreshCw className="h-4 w-4" />
                        Повторить
                      </button>
                    ) : null}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </Card>
      <RenderLocalSwitchModal
        offer={localOffer}
        busy={localOfferBusy}
        onCancel={() => {
          if (localOffer) dismissLocalOffer(localOffer.job_id);
          setLocalOffer(null);
        }}
        onConfirm={() => {
          if (!localOffer) return;
          const jobId = localOffer.job_id;
          setLocalOfferBusy(true);
          void (async () => {
            try {
              const row = await retryGenerationOnLocal(jobId);
              setLocalOffer(null);
              dismissLocalOffer(jobId);
              await reload();
              if (row.status === "done") {
                push(`Рендер #${jobId} готов на local`, "success");
              } else {
                push(withLocalRenderHint(row.last_error || `Рендер #${jobId}: ${row.status}`), "error");
              }
            } catch (err) {
              push(withLocalRenderHint(formatApiError(err)), "error");
            } finally {
              setLocalOfferBusy(false);
            }
          })();
        }}
      />
    </div>
  );
}
