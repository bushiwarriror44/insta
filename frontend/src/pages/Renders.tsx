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
  clipboardMediaFile,
  modeForMedia,
  uploadRenderReference,
  type RenderInputMode,
  type RenderReference,
} from "../lib/referenceUpload";
import type { AccountOut, RenderBackendOut } from "../api/types";

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

function referenceMismatch(reference: RenderReference | null, inputMode: RenderInputMode): string | null {
  if (!reference) return null;
  if (inputMode === "image_slideshow" && reference.mediaType !== "image") {
    return "Ken Burns работает только с фото. Выберите изображение или режим «По видео».";
  }
  if (inputMode === "video_to_video" && reference.mediaType !== "video") {
    return "Режим «По видео» нужен короткий ролик. Для картинки выберите «По фото».";
  }
  if (inputMode === "image_to_video" && reference.mediaType !== "image") {
    return "Режим «По фото» нужен кадр-картинку. Для ролика выберите «По видео».";
  }
  return null;
}

function referenceBackendNote(
  backends: RenderBackendOut[],
  backend: string,
  reference: RenderReference | null,
  inputMode: RenderInputMode
): string | null {
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
  const [backend, setBackend] = useState("auto");
  const [accountId, setAccountId] = useState<number | "">("");
  const [frameId, setFrameId] = useState<(typeof FRAME_SIZES)[number]["id"]>("9:16-720");
  const [durationS, setDurationS] = useState<DurationS>(5);
  const [negativePrompt, setNegativePrompt] = useState("");
  const [seed, setSeed] = useState("");
  const [platform, setPlatform] = useState<(typeof PLATFORMS)[number]["id"]>("");
  const [joinIds, setJoinIds] = useState("");
  const [libraryFiles, setLibraryFiles] = useState<Array<{ filename: string; media_type: string }>>([]);
  const [reference, setReference] = useState<RenderReference | null>(null);
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
    const [g, c, accs, engines, uploads] = await Promise.all([
      api.factory.generations(),
      api.factory.compositions(),
      api.accounts.list(),
      api.factory.backends(),
      api.videos.list().catch(() => []),
    ]);
    setGens(g);
    setJoins(c);
    setAccounts(accs);
    setBackends(engines);
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

  return (
    <div className="space-y-6">
      <PageHeader icon={Clapperboard} title="Рендеры и склейки" />
      <Card>
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
            onPaste={(event) => {
              const file = clipboardMediaFile(event.nativeEvent);
              if (!file || !file.type.startsWith("image/")) return;
              event.preventDefault();
              setUploadingReference(true);
              void uploadRenderReference(file)
                .then((next) => {
                  setReference(next);
                  setInputMode(modeForMedia(next.mediaType));
                  setLibraryFiles((prev) =>
                    prev.some((item) => item.filename === next.filename)
                      ? prev
                      : [...prev, { filename: next.filename, media_type: next.mediaType }]
                  );
                })
                .catch((err) => push(formatApiError(err), "error"))
                .finally(() => setUploadingReference(false));
            }}
          />
          <span className="mt-1 block text-xs text-slate-500">
            Ctrl+V — вставить картинку как пример кадра
          </span>
        </label>
        <RenderReferenceField
          value={reference}
          libraryFiles={libraryFiles}
          inputMode={inputMode}
          disabled={uploadingReference}
          backendNote={referenceBackendNote(backends, backend, reference, inputMode)}
          onChange={(next) => {
            setReference(next);
            if (!next) return;
            setLibraryFiles((prev) =>
              prev.some((item) => item.filename === next.filename)
                ? prev
                : [...prev, { filename: next.filename, media_type: next.mediaType }]
            );
          }}
          onInputModeChange={setInputMode}
        />
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
          <label className="block text-sm text-slate-200">
            Негативный промпт
            <input
              className="input mt-1"
              aria-label="Негативный промпт"
              placeholder="текст, логотип, лишние руки"
              value={negativePrompt}
              onChange={(e) => setNegativePrompt(e.target.value)}
            />
          </label>
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
        <p className="text-xs text-slate-500">
          {shortDurationOnly(backend, inputMode)
            ? "Local Wan длиннее 10 с не снимет. 480p: портрет 480×832, альбом 832×480."
            : backend === "fal"
              ? "fal снимет 5 или 10 с, ближайшее к выбранному."
              : "Локальный Wan 1.3B снимает 480p и только 5 или 10 с. Размер выше задаёт ориентацию."}
          {platform ? " 9:16, звук и поля под кнопки платформы. Файл остаётся mp4." : ""}
        </p>
        <button
          className="btn-primary"
          disabled={!prompt.trim() || uploadingReference}
          onClick={async () => {
            const mismatch = referenceMismatch(reference, inputMode);
            if (mismatch) {
              push(mismatch, "error");
              return;
            }
            try {
              const ref = reference?.filename ?? "";
              const role = reference?.mediaType === "video" ? "motion_video" : "start_image";
              const frame = FRAME_SIZES.find((size) => size.id === frameId) ?? FRAME_SIZES[0];
              const seedNumber = seed.trim() ? Number(seed) : undefined;
              const created = await api.factory.createGeneration({
                prompt: prompt.trim(),
                backend: inputMode === "image_slideshow" ? "slideshow" : backend,
                account_id: typeof accountId === "number" ? accountId : undefined,
                width: frame.width,
                height: frame.height,
                duration_s: durationS,
                ...(negativePrompt.trim() ? { negative_prompt: negativePrompt.trim() } : {}),
                ...(seedNumber !== undefined ? { seed: seedNumber } : {}),
                ...(ref
                  ? {
                      input_mode: inputMode || undefined,
                      reference_filename: ref,
                      reference_role: role,
                    }
                  : {}),
              });
              setPrompt("");
              setReference(null);
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
          }}
        >
          <Play className="h-4 w-4" />
          Поставить рендер
        </button>
      </Card>
      <Card>
        <h2 className="font-medium mb-3">Рендеры</h2>
        <table className="table-base">
          <thead>
            <tr>
              <th>ID</th>
              <th>Статус</th>
              <th>Бэкенд</th>
              <th>Заголовок</th>
              <th>Стадия</th>
              <th>Ошибка</th>
              <th>$</th>
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
                <td>{g.backend || "—"}</td>
                <td className="truncate" title={g.post_title || g.prompt}>
                  {g.post_title || g.prompt.slice(0, 60)}
                </td>
                <td className="min-w-[8rem]">
                  <p className="truncate text-xs text-slate-300" title={generationStageLabel(g.status, g.stage, g.queue_position)}>
                    {generationStageLabel(g.status, g.stage, g.queue_position)}
                  </p>
                  {!isTerminalGeneration(g.status) ? <GenerationStagePulse /> : null}
                </td>
                <td
                  className={clsx(
                    "max-w-[200px] truncate text-xs",
                    ["failed", "dead"].includes(g.status) && g.last_error ? "text-rose-300" : "text-slate-500"
                  )}
                  title={["failed", "dead"].includes(g.status) ? g.last_error || undefined : undefined}
                >
                  {["failed", "dead"].includes(g.status) ? g.last_error || "—" : "—"}
                </td>
                <td className="tabular-nums">{g.cost_usd}</td>
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
      </Card>
      <Card>
        <h2 className="font-medium">Склейки</h2>
        <div className="flex gap-2">
          <input className="input" placeholder="id клипов через запятую" value={joinIds} onChange={(e) => setJoinIds(e.target.value)} />
          <button
            className="btn-ghost shrink-0"
            onClick={async () => {
              const clip_ids = joinIds.split(",").map((s) => Number(s.trim())).filter(Boolean);
              if (clip_ids.length < 2) {
                push("Нужны минимум два id клипов через запятую", "error");
                return;
              }
              try {
                const created = await api.factory.createComposition({
                  clip_ids,
                  account_id: typeof accountId === "number" ? accountId : undefined,
                });
                setJoinIds("");
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
            }}
          >
            <Layers className="h-4 w-4" />
            Склеить
          </button>
        </div>
        <table className="table-base">
          <thead>
            <tr>
              <th>ID</th>
              <th>Статус</th>
              <th>Пост</th>
              <th>Клипов</th>
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
                <td className="tabular-nums">{j.clips}</td>
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
