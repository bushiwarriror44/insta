import {
  Check,
  ExternalLink,
  Loader2,
  Plus,
  RefreshCw,
  Trash2,
  Wand2,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import clsx from "clsx";

import { api, formatApiError } from "../api/client";
import type {
  QubaxBatchVariantIn,
  QubaxEstimateOut,
  QubaxFormState,
  QubaxJobOut,
  QubaxMarketModelOut,
  QubaxModelOut,
  QubaxStatusOut,
} from "../api/types";
import { useConfirm } from "../context/ConfirmContext";
import { usePollWhenVisible } from "../hooks/usePollWhenVisible";
import { useToast } from "../context/ToastContext";
import { EmptyState } from "./EmptyState";

const DURATIONS = ["3s", "5s", "10s", "15s"] as const;
const ASPECTS = ["9:16", "16:9", "1:1", "4:3", "3:4"] as const;

const PROMPT_TEMPLATES: { label: string; text: string; aspect: string }[] = [
  {
    label: "Reels 9:16",
    aspect: "9:16",
    text: "Вертикальное видео для Reels, кинематографичный свет, плавное движение камеры, без текста и логотипов",
  },
  {
    label: "Shorts 16:9",
    aspect: "16:9",
    text: "Горизонтальный ролик для YouTube Shorts, динамичный монтаж, чёткая картинка, без субтитров",
  },
  {
    label: "TikTok",
    aspect: "9:16",
    text: "Энергичное вертикальное видео, крупный план, естественные цвета, без водяных знаков",
  },
];

type VariantRow = QubaxBatchVariantIn & { key: string };

function formatMoney(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—";
  return n < 0.1 ? `$${n.toFixed(4)}` : `$${n.toFixed(2)}`;
}

function formatUnitPrice(price: number | null | undefined, unit: string | null | undefined): string {
  if (price == null || !Number.isFinite(price)) return "—";
  const u = (unit || "job").toLowerCase();
  if (u === "second") return `${formatMoney(price)}/сек`;
  return `${formatMoney(price)}/видео`;
}

function chipPriceLabel(id: string, prices: Record<string, QubaxMarketModelOut>): string {
  const row = prices[id];
  if (row?.price == null) return "";
  return formatUnitPrice(row.price, row.unit ?? "job");
}

function jobStatusLabel(status: string): string {
  const s = status.toLowerCase();
  if (s === "completed") return "Готово";
  if (s === "failed" || s === "error") return "Ошибка";
  if (s === "processing" || s === "running") return "Рендер";
  return "В очереди";
}

function isTerminal(status: string): boolean {
  const s = status.toLowerCase();
  return s === "completed" || s === "failed" || s === "error" || s === "cancelled";
}

let variantKey = 0;
function newVariant(model: string, duration: string, aspect: string): VariantRow {
  variantKey += 1;
  return { key: `v-${variantKey}`, model, duration, aspect_ratio: aspect };
}

export function QubaxPanel() {
  const { push } = useToast();
  const confirm = useConfirm();
  const [status, setStatus] = useState<QubaxStatusOut | null>(null);
  const [apiKeyDraft, setApiKeyDraft] = useState("");
  const [statusBusy, setStatusBusy] = useState(false);
  const [presets, setPresets] = useState<QubaxModelOut[]>([]);
  const [allModels, setAllModels] = useState<QubaxModelOut[]>([]);
  const [modelTab, setModelTab] = useState<"presets" | "all">("presets");
  const [modelQuery, setModelQuery] = useState("");
  const [mode, setMode] = useState<"t2v" | "i2v">("t2v");
  const [model, setModel] = useState("kling-v3-standard-text-to-video");
  const [prompt, setPrompt] = useState("");
  const [duration, setDuration] = useState<string>("5s");
  const [aspect, setAspect] = useState<string>("9:16");
  const [imageFilename, setImageFilename] = useState("");
  const [imageOptions, setImageOptions] = useState<string[]>([]);
  const [variants, setVariants] = useState<VariantRow[]>([]);
  const [selectedPresets, setSelectedPresets] = useState<Set<string>>(new Set());
  const [jobs, setJobs] = useState<QubaxJobOut[]>([]);
  const [submitBusy, setSubmitBusy] = useState(false);
  const [importBusy, setImportBusy] = useState<number | null>(null);
  const [panelPublicUrl, setPanelPublicUrl] = useState("");
  const [defaultModel, setDefaultModel] = useState("kling-v3-standard-text-to-video");
  const [defaultModelI2v, setDefaultModelI2v] = useState("uncensored-i2v-pro");
  const [priceMap, setPriceMap] = useState<Record<string, QubaxMarketModelOut>>({});
  const [singleEstimate, setSingleEstimate] = useState<QubaxEstimateOut | null>(null);
  const [batchEstimate, setBatchEstimate] = useState<QubaxEstimateOut | null>(null);
  const [modelMarket, setModelMarket] = useState<QubaxMarketModelOut | null>(null);
  const [allowedDurations, setAllowedDurations] = useState<string[] | null>(null);
  const [allowedAspects, setAllowedAspects] = useState<string[] | null>(null);
  const formHydrated = useRef(false);
  const skipAutosave = useRef(true);

  const applyLastForm = useCallback((lf: QubaxFormState | null | undefined) => {
    if (!lf) return;
    if (lf.prompt != null) setPrompt(lf.prompt);
    if (lf.model) setModel(lf.model);
    if (lf.duration) setDuration(lf.duration);
    if (lf.aspect_ratio) setAspect(lf.aspect_ratio);
    if (lf.image_filename) setImageFilename(lf.image_filename);
    if (lf.mode === "i2v" || lf.mode === "t2v") setMode(lf.mode);
    if (lf.model_tab === "all" || lf.model_tab === "presets") setModelTab(lf.model_tab);
    if (lf.selected_presets?.length) setSelectedPresets(new Set(lf.selected_presets));
    if (lf.variants?.length) {
      setVariants(
        lf.variants.map((v, i) => ({
          key: `restored-${i}`,
          model: v.model,
          duration: v.duration || lf.duration || "5s",
          aspect_ratio: v.aspect_ratio || lf.aspect_ratio || "9:16",
        }))
      );
    } else if (lf.variant_models?.length) {
      setVariants(
        lf.variant_models.map((m, i) => ({
          key: `restored-${i}`,
          model: m,
          duration: lf.duration || "5s",
          aspect_ratio: lf.aspect_ratio || "9:16",
        }))
      );
    }
    if (lf.api_public_base_url != null) setPanelPublicUrl(lf.api_public_base_url);
    if (lf.default_model) setDefaultModel(lf.default_model);
    if (lf.default_model_i2v) setDefaultModelI2v(lf.default_model_i2v);
  }, []);

  const buildFormState = useCallback((): QubaxFormState => {
    return {
      mode,
      model,
      prompt,
      duration,
      aspect_ratio: aspect,
      image_filename: imageFilename || null,
      variants: variants.map((v) => ({
        model: v.model,
        duration: v.duration,
        aspect_ratio: v.aspect_ratio,
      })),
      variant_models: variants.map((v) => v.model),
      selected_presets: [...selectedPresets],
      model_tab: modelTab,
      api_public_base_url: panelPublicUrl.trim() || null,
      default_model: defaultModel.trim() || null,
      default_model_i2v: defaultModelI2v.trim() || null,
    };
  }, [
    mode,
    model,
    prompt,
    duration,
    aspect,
    imageFilename,
    variants,
    selectedPresets,
    modelTab,
    panelPublicUrl,
    defaultModel,
    defaultModelI2v,
  ]);

  const refreshStatus = useCallback(async () => {
    setStatusBusy(true);
    try {
      const next = await api.qubax.status();
      setStatus(next);
      if (!formHydrated.current) {
        applyLastForm(next.last_form);
        if (!next.last_form?.default_model && next.settings?.default_model) {
          setDefaultModel(next.settings.default_model);
        }
        if (!next.last_form?.default_model_i2v && next.settings?.default_model_i2v) {
          setDefaultModelI2v(next.settings.default_model_i2v);
        }
        formHydrated.current = true;
        window.setTimeout(() => {
          skipAutosave.current = false;
        }, 100);
      }
      return next;
    } catch (err) {
      push(formatApiError(err), "error");
      return null;
    } finally {
      setStatusBusy(false);
    }
  }, [push, applyLastForm]);

  const loadModels = useCallback(async () => {
    if (!status?.configured) return;
    try {
      const [out, prices] = await Promise.all([api.qubax.models(), api.qubax.marketPrices()]);
      setPresets(out.presets || []);
      setAllModels(out.models || []);
      setPriceMap(prices.prices || {});
    } catch (err) {
      push(formatApiError(err), "error");
    }
  }, [status?.configured, push]);

  const batchVariantLines = useMemo((): QubaxBatchVariantIn[] => {
    const fromRows = variants.map(({ model: m, duration: d, aspect_ratio, batch_label }) => ({
      model: m,
      duration: d,
      aspect_ratio,
      batch_label,
    }));
    const fromPresets = [...selectedPresets].map((id) => ({
      model: id,
      duration,
      aspect_ratio: aspect,
    }));
    return [...fromRows, ...fromPresets];
  }, [variants, selectedPresets, duration, aspect]);

  const applySuggestedPublicUrl = useCallback(() => {
    const url = status?.settings?.suggested_api_public_base_url?.trim();
    if (!url) {
      push("Не удалось определить публичный URL с сервера", "error");
      return;
    }
    setPanelPublicUrl(url);
    push("Публичный URL подставлен — сохраняется автоматически", "success");
  }, [status?.settings?.suggested_api_public_base_url, push]);

  const applyTabOriginUrl = useCallback(() => {
    setPanelPublicUrl(window.location.origin);
    push("Подставлен origin этой вкладки", "success");
  }, [push]);

  const loadJobs = useCallback(async () => {
    if (!status?.configured) return;
    try {
      const out = await api.qubax.listJobs({ limit: 50 });
      setJobs(out.items || []);
    } catch (err) {
      push(formatApiError(err), "error");
    }
  }, [status?.configured, push]);

  const loadImages = useCallback(async () => {
    try {
      const list = await api.videos.list();
      const names = list
        .filter((f) => (f.media_type || "").toLowerCase() === "image")
        .map((f) => f.filename);
      setImageOptions(names);
    } catch {
      setImageOptions([]);
    }
  }, []);

  useEffect(() => {
    void refreshStatus();
    void loadImages();
  }, [refreshStatus, loadImages]);

  useEffect(() => {
    void loadModels();
  }, [loadModels]);

  useEffect(() => {
    void loadJobs();
  }, [loadJobs]);

  const activeJobs = useMemo(
    () => jobs.filter((j) => !isTerminal(j.status)),
    [jobs]
  );

  const pollActive = useCallback(async () => {
    if (!status?.configured) return;
    try {
      const out = await api.qubax.listJobs({ limit: 50, sync_active: true });
      setJobs(out.items || []);
    } catch {
      // ignore poll errors
    }
  }, [status?.configured]);

  usePollWhenVisible(pollActive, 5000, Boolean(status?.configured && activeJobs.length));

  useEffect(() => {
    if (!status?.configured || skipAutosave.current) return;
    const handle = window.setTimeout(() => {
      void api.qubax.saveForm(buildFormState()).catch(() => {});
    }, 800);
    return () => window.clearTimeout(handle);
  }, [status?.configured, buildFormState]);

  useEffect(() => {
    if (!status?.configured || !model) return;
    void api.qubax
      .modelDetail(model)
      .then((detail) => {
        const caps = detail as {
          durations?: string[];
          supported_durations?: string[];
          aspect_ratios?: string[];
          supported_aspect_ratios?: string[];
          market?: QubaxMarketModelOut;
          price?: number;
          unit?: string;
        };
        const market =
          caps.market ||
          ({
            id: model,
            price: caps.price ?? null,
            unit: caps.unit ?? null,
          } as QubaxMarketModelOut);
        setModelMarket(market);
        const durs = caps.durations || caps.supported_durations;
        const aspects = caps.aspect_ratios || caps.supported_aspect_ratios;
        setAllowedDurations(Array.isArray(durs) ? durs.map(String) : null);
        setAllowedAspects(Array.isArray(aspects) ? aspects.map(String) : null);
      })
      .catch(() => {
        setModelMarket(null);
        setAllowedDurations(null);
        setAllowedAspects(null);
      });
  }, [model, status?.configured]);

  useEffect(() => {
    if (!status?.configured) {
      setSingleEstimate(null);
      setBatchEstimate(null);
      return;
    }
    const handle = window.setTimeout(() => {
      void api.qubax
        .estimate({
          include_single: true,
          model,
          duration,
          aspect_ratio: aspect,
          variants: [],
        })
        .then(setSingleEstimate)
        .catch(() => setSingleEstimate(null));
    }, 450);
    return () => window.clearTimeout(handle);
  }, [status?.configured, model, duration, aspect]);

  const batchEstimateKey = useMemo(
    () =>
      JSON.stringify(
        batchVariantLines.map((v) => [v.model, v.duration || duration, v.aspect_ratio || aspect])
      ),
    [batchVariantLines, duration, aspect]
  );

  useEffect(() => {
    if (!status?.configured || !batchVariantLines.length) {
      setBatchEstimate(null);
      return;
    }
    const lines = batchVariantLines;
    const handle = window.setTimeout(() => {
      void api.qubax
        .estimate({
          include_single: false,
          duration,
          aspect_ratio: aspect,
          variants: lines,
        })
        .then(setBatchEstimate)
        .catch(() => setBatchEstimate(null));
    }, 450);
    return () => window.clearTimeout(handle);
  }, [status?.configured, batchEstimateKey, batchVariantLines, duration, aspect]);

  const durationEnabled = useCallback(
    (d: string) => !allowedDurations?.length || allowedDurations.includes(d),
    [allowedDurations]
  );

  const aspectEnabled = useCallback(
    (a: string) => !allowedAspects?.length || allowedAspects.includes(a),
    [allowedAspects]
  );

  const warnIfInsufficient = useCallback(
    async (est: QubaxEstimateOut | null) => {
      if (est?.sufficient === false) {
        return confirm({
          title: "Недостаточно средств",
          body: `Оценка ${formatMoney(est.total_usd ?? null)}, баланс ${formatMoney(est.balance_usd ?? status?.balance ?? null)}. Продолжить?`,
          confirmLabel: "Всё равно запустить",
          danger: true,
        });
      }
      return true;
    },
    [confirm, status?.balance]
  );

  const visibleModels = useMemo(() => {
    const source = modelTab === "presets" ? presets : allModels;
    const q = modelQuery.trim().toLowerCase();
    if (!q) return source;
    return source.filter(
      (m) =>
        m.id.toLowerCase().includes(q) ||
        (m.label || "").toLowerCase().includes(q)
    );
  }, [modelTab, presets, allModels, modelQuery]);

  const saveKey = async () => {
    try {
      const next = await api.qubax.setApiKey(apiKeyDraft.trim());
      setStatus(next);
      setApiKeyDraft("");
      push("Ключ Qubax сохранён", "success");
      void loadModels();
    } catch (err) {
      push(formatApiError(err), "error");
    }
  };

  const runSingle = async () => {
    if (!prompt.trim()) {
      push("Введите промпт", "error");
      return;
    }
    if (!(await warnIfInsufficient(singleEstimate))) return;
    setSubmitBusy(true);
    try {
      const job = await api.qubax.createJob({
        model,
        prompt: prompt.trim(),
        duration,
        aspect_ratio: aspect,
        image_filename: mode === "i2v" ? imageFilename || null : null,
      });
      setJobs((prev) => [job, ...prev]);
      push("Задача отправлена в Qubax", "success");
    } catch (err) {
      push(formatApiError(err), "error");
    } finally {
      setSubmitBusy(false);
    }
  };

  const runBatch = async () => {
    if (!prompt.trim()) {
      push("Введите промпт", "error");
      return;
    }
    let batch: QubaxBatchVariantIn[] = variants.map(({ model: m, duration: d, aspect_ratio, batch_label }) => ({
      model: m,
      duration: d,
      aspect_ratio,
      batch_label,
    }));
    if (selectedPresets.size) {
      batch = [
        ...batch,
        ...[...selectedPresets].map((id) => ({ model: id, duration, aspect_ratio: aspect })),
      ];
    }
    if (!batch.length) {
      push("Добавьте варианты или отметьте пресеты", "error");
      return;
    }
    if (!(await warnIfInsufficient(batchEstimate))) return;
    setSubmitBusy(true);
    try {
      const out = await api.qubax.createBatch({
        prompt: prompt.trim(),
        variants: batch,
        image_filename: mode === "i2v" ? imageFilename || null : null,
      });
      setJobs((prev) => [...out.items, ...prev]);
      push(`Запущено вариантов: ${out.total}`, "success");
    } catch (err) {
      push(formatApiError(err), "error");
    } finally {
      setSubmitBusy(false);
    }
  };

  const importJob = async (id: number) => {
    setImportBusy(id);
    try {
      const out = await api.qubax.importJob(id);
      push(`В библиотеке: ${out.filename}`, "success");
      void loadJobs();
    } catch (err) {
      push(formatApiError(err), "error");
    } finally {
      setImportBusy(null);
    }
  };

  const togglePreset = (id: string) => {
    setSelectedPresets((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div className="space-y-6" data-testid="qubax-panel">
      <section className="card space-y-3 p-4 ring-1 ring-slate-800">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="text-sm font-medium text-slate-100">API-ключ Qubax</div>
          <div className="flex flex-wrap items-center gap-3">
            <a
              href="https://qubax.ai"
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-xs text-brand-300 hover:underline"
            >
              qubax.ai <ExternalLink size={12} />
            </a>
            <a
              href={status?.settings?.docs_url || "https://qubax.ai/docs"}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-xs text-brand-300 hover:underline"
            >
              Документация <ExternalLink size={12} />
            </a>
          </div>
        </div>
        {status?.key_from_env ? (
          <p className="text-sm text-slate-400">Ключ задан через QUBAX_API_KEY (из панели не меняется).</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            <input
              type="password"
              className="input min-w-[220px] flex-1"
              placeholder="qbx_live_…"
              value={apiKeyDraft}
              onChange={(e) => setApiKeyDraft(e.target.value)}
              data-testid="qubax-api-key"
            />
            <button type="button" className="btn-primary" onClick={() => void saveKey()} disabled={!apiKeyDraft.trim()}>
              Сохранить
            </button>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-3 text-sm text-slate-400">
          <button
            type="button"
            className="inline-flex items-center gap-1 hover:text-slate-200"
            onClick={() => void refreshStatus()}
            disabled={statusBusy}
          >
            <RefreshCw size={14} className={statusBusy ? "animate-spin" : ""} />
            Обновить
          </button>
          <span>
            Статус: {status?.configured ? "подключено" : "нет ключа"}
            {status?.configured ? ` · баланс ${formatMoney(status.balance ?? null)}` : ""}
          </span>
          {status?.error ? (
            <span className="text-rose-400">
              {status.error.includes("402")
                ? "Недостаточно средств — пополните баланс на qubax.ai"
                : status.error}
            </span>
          ) : null}
        </div>
        {status?.configured ? (
          <div className="space-y-2 border-t border-slate-800 pt-3 text-sm">
            <div className="font-medium text-slate-200">Настройки панели</div>
            <label className="block text-xs text-slate-400">
              Публичный URL API (для I2V)
              <input
                className="input mt-1 w-full text-sm"
                placeholder="https://your-panel.example.com"
                value={panelPublicUrl}
                onChange={(e) => setPanelPublicUrl(e.target.value)}
                data-testid="qubax-public-url"
              />
            </label>
            {status.settings?.suggested_api_public_base_url ? (
              <p className="text-xs text-slate-500">
                Предложение с сервера: {status.settings.suggested_api_public_base_url}
              </p>
            ) : null}
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className="btn-secondary text-xs"
                data-testid="qubax-apply-public-url"
                onClick={applySuggestedPublicUrl}
                disabled={!status.settings?.suggested_api_public_base_url}
              >
                Встроить автоматически
              </button>
              <button type="button" className="btn-ghost text-xs" onClick={applyTabOriginUrl}>
                Origin вкладки
              </button>
            </div>
            {status.settings?.api_public_source === "env" ? (
              <p className="text-xs text-slate-500">
                Сейчас используется API_PUBLIC_BASE_URL из окружения (сильнее настроек панели).
              </p>
            ) : status.settings?.api_public_source === "panel" ? (
              <p className="text-xs text-slate-500">Источник: настройки панели.</p>
            ) : null}
            {status.settings?.api_public_configured ? (
              <p className="text-xs text-emerald-500/80">I2V: публичный доступ к кадрам настроен.</p>
            ) : (
              <p className="text-xs text-amber-500/90">
                Для фото→видео укажите URL, по которому Qubax достучится до API.
              </p>
            )}
            <div className="grid gap-2 sm:grid-cols-2">
              <label className="block text-xs text-slate-400">
                Модель T2V (Рендеры)
                <input
                  className="input mt-1 w-full text-sm"
                  value={defaultModel}
                  onChange={(e) => setDefaultModel(e.target.value)}
                />
              </label>
              <label className="block text-xs text-slate-400">
                Модель I2V (Рендеры)
                <input
                  className="input mt-1 w-full text-sm"
                  value={defaultModelI2v}
                  onChange={(e) => setDefaultModelI2v(e.target.value)}
                />
              </label>
            </div>
          </div>
        ) : null}
      </section>

      {!status?.configured ? (
        <EmptyState title="Нужен API-ключ">Сохраните ключ Qubax выше, чтобы генерировать видео.</EmptyState>
      ) : (
        <>
          <section className="card space-y-4 p-4">
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className={clsx("rounded-full px-3 py-1 text-xs ring-1", mode === "t2v" ? "bg-brand-600/20 ring-brand-500/50" : "ring-slate-700")}
                onClick={() => setMode("t2v")}
              >
                Текст → видео
              </button>
              <button
                type="button"
                className={clsx("rounded-full px-3 py-1 text-xs ring-1", mode === "i2v" ? "bg-brand-600/20 ring-brand-500/50" : "ring-slate-700")}
                onClick={() => setMode("i2v")}
              >
                Фото → видео
              </button>
            </div>
            {mode === "i2v" ? (
              <label className="block text-sm text-slate-300">
                Кадр из библиотеки
                <select
                  className="input mt-1 w-full"
                  value={imageFilename}
                  onChange={(e) => setImageFilename(e.target.value)}
                >
                  <option value="">— выберите изображение —</option>
                  {imageOptions.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
                <p className="mt-1 text-xs text-slate-500">
                  Для I2V нужен публичный API (API_PUBLIC_BASE_URL).{" "}
                  <Link to="/publishing" className="text-brand-300 hover:underline">
                    Загрузите фото в библиотеку
                  </Link>
                </p>
              </label>
            ) : null}
            <div className="space-y-2">
              <div className="flex gap-2 text-sm">
                <button
                  type="button"
                  className={clsx("rounded px-2 py-0.5", modelTab === "presets" ? "bg-slate-700" : "")}
                  onClick={() => setModelTab("presets")}
                >
                  Пресеты
                </button>
                <button
                  type="button"
                  className={clsx("rounded px-2 py-0.5", modelTab === "all" ? "bg-slate-700" : "")}
                  onClick={() => setModelTab("all")}
                >
                  Все модели
                </button>
              </div>
              <input
                className="input w-full text-sm"
                placeholder="Поиск модели…"
                value={modelQuery}
                onChange={(e) => setModelQuery(e.target.value)}
              />
              <div className="flex max-h-36 flex-wrap gap-2 overflow-y-auto">
                {visibleModels.map((m) => (
                  <button
                    key={m.id}
                    type="button"
                    onClick={() => setModel(m.id)}
                    className={clsx(
                      "rounded-lg px-2 py-1 text-left text-xs ring-1",
                      model === m.id ? "bg-brand-600/25 ring-brand-500/50" : "ring-slate-700 hover:bg-slate-800"
                    )}
                  >
                    <span>{m.label || m.id}</span>
                    {chipPriceLabel(m.id, priceMap) ? (
                      <span className="ml-1 text-[10px] text-slate-400">{chipPriceLabel(m.id, priceMap)}</span>
                    ) : null}
                  </button>
                ))}
              </div>
            </div>
            <div
              className="rounded-lg border border-slate-800 bg-slate-900/50 p-3 text-sm"
              data-testid="qubax-cost-card"
            >
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <span className="font-medium text-slate-200">Стоимость</span>
                <a
                  href={`https://qubax.ai/models/${encodeURIComponent(model)}`}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-xs text-brand-300 hover:underline"
                >
                  Модель на Qubax <ExternalLink size={12} />
                </a>
              </div>
              <p className="text-xs text-slate-400">
                {modelMarket?.price != null ? (
                  <>
                    {formatUnitPrice(modelMarket.price, modelMarket.unit)}
                    {modelMarket.discount_pct != null ? (
                      <span className="ml-2 text-emerald-400/90">−{modelMarket.discount_pct.toFixed(0)}%</span>
                    ) : null}
                  </>
                ) : (
                  "Цена подгружается…"
                )}
              </p>
              <p className="mt-1 text-xs text-slate-300">
                Одна генерация: {formatMoney(singleEstimate?.total_usd ?? singleEstimate?.items?.[0]?.line_cost ?? null)}
              </p>
              {batchEstimate && batchEstimate.jobs_count > 0 ? (
                <p className="mt-1 text-xs text-slate-300">
                  Пакет ({batchEstimate.jobs_count}): {formatMoney(batchEstimate.total_usd ?? null)}
                  {batchEstimate.sufficient === false ? (
                    <span className="ml-2 text-amber-400">баланса может не хватить</span>
                  ) : null}
                </p>
              ) : null}
              {singleEstimate?.balance_usd != null && singleEstimate.total_usd != null ? (
                <p className="mt-1 text-xs text-slate-500">
                  После одной генерации останется ~
                  {formatMoney(singleEstimate.balance_usd - singleEstimate.total_usd)}
                </p>
              ) : null}
            </div>
            <label className="block text-sm text-slate-200">
              Промпт
              <textarea
                className="input mt-1 min-h-[88px]"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                data-testid="qubax-prompt"
              />
            </label>
            <div className="flex flex-wrap gap-2">
              {PROMPT_TEMPLATES.map((t) => (
                <button
                  key={t.label}
                  type="button"
                  className="rounded-full bg-slate-800 px-2 py-0.5 text-xs text-slate-300"
                  onClick={() => {
                    setPrompt(t.text);
                    setAspect(t.aspect);
                  }}
                >
                  {t.label}
                </button>
              ))}
            </div>
            <div className="flex flex-wrap gap-4">
              <div>
                <div className="mb-1 text-xs text-slate-400">Длительность</div>
                <div className="flex flex-wrap gap-1">
                  {DURATIONS.map((d) => (
                    <button
                      key={d}
                      type="button"
                      disabled={!durationEnabled(d)}
                      className={clsx(
                        "rounded px-2 py-0.5 text-xs ring-1",
                        duration === d ? "bg-brand-600/20 ring-brand-500/40" : "ring-slate-700",
                        !durationEnabled(d) && "cursor-not-allowed opacity-40"
                      )}
                      onClick={() => setDuration(d)}
                    >
                      {d}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <div className="mb-1 text-xs text-slate-400">Соотношение</div>
                <div className="flex flex-wrap gap-1">
                  {ASPECTS.map((a) => (
                    <button
                      key={a}
                      type="button"
                      disabled={!aspectEnabled(a)}
                      className={clsx(
                        "rounded px-2 py-0.5 text-xs ring-1",
                        aspect === a ? "bg-brand-600/20 ring-brand-500/40" : "ring-slate-700",
                        !aspectEnabled(a) && "cursor-not-allowed opacity-40"
                      )}
                      onClick={() => setAspect(a)}
                    >
                      {a}
                    </button>
                  ))}
                </div>
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <button type="button" className="btn-primary" disabled={submitBusy} onClick={() => void runSingle()}>
                {submitBusy ? <Loader2 className="animate-spin" size={16} /> : <Wand2 size={16} />}
                Сгенерировать
              </button>
            </div>
          </section>

          <section className="card space-y-3 p-4">
            <h3 className="text-sm font-medium">Несколько вариантов</h3>
            <p className="text-xs text-slate-400">
              Отметьте пресеты для сравнения или добавьте строки с разными моделями.
            </p>
            <div className="flex flex-wrap gap-2">
              {presets.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => togglePreset(p.id)}
                  className={clsx(
                    "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs ring-1",
                    selectedPresets.has(p.id) ? "bg-emerald-900/40 ring-emerald-500/50" : "ring-slate-700"
                  )}
                >
                  {selectedPresets.has(p.id) ? <Check size={12} /> : null}
                  {p.label || p.id}
                  {chipPriceLabel(p.id, priceMap) ? (
                    <span className="text-[10px] text-slate-400">{chipPriceLabel(p.id, priceMap)}</span>
                  ) : null}
                </button>
              ))}
            </div>
            <div className="space-y-2">
              {variants.map((row) => (
                <div key={row.key} className="flex flex-wrap items-center gap-2">
                  <input
                    className="input min-w-[180px] flex-1 text-xs"
                    value={row.model}
                    onChange={(e) =>
                      setVariants((prev) =>
                        prev.map((v) => (v.key === row.key ? { ...v, model: e.target.value } : v))
                      )
                    }
                  />
                  <select
                    className="input text-xs"
                    value={row.duration || duration}
                    onChange={(e) =>
                      setVariants((prev) =>
                        prev.map((v) => (v.key === row.key ? { ...v, duration: e.target.value } : v))
                      )
                    }
                  >
                    {DURATIONS.map((d) => (
                      <option key={d} value={d}>
                        {d}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="btn-ghost p-1"
                    aria-label="Удалить"
                    onClick={() => setVariants((prev) => prev.filter((v) => v.key !== row.key))}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              ))}
              <button
                type="button"
                className="inline-flex items-center gap-1 text-xs text-brand-300"
                onClick={() => setVariants((prev) => [...prev, newVariant(model, duration, aspect)])}
              >
                <Plus size={14} /> Добавить вариант
              </button>
            </div>
            <button
              type="button"
              className="btn-secondary"
              data-testid="qubax-batch"
              disabled={submitBusy}
              onClick={() => void runBatch()}
            >
              Запустить варианты
            </button>
          </section>

          <section className="card space-y-3 p-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium">Задачи</h3>
              <button type="button" className="btn-ghost text-xs" onClick={() => void loadJobs()}>
                Обновить
              </button>
            </div>
            {!jobs.length ? (
              <p className="text-sm text-slate-500">Пока нет генераций.</p>
            ) : (
              <ul className="space-y-3">
                {jobs.map((job) => (
                  <li key={job.id} className="rounded-lg bg-slate-900/60 p-3 text-sm" data-testid={`qubax-job-${job.id}`}>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="font-medium text-slate-200">{job.model}</span>
                      <span
                        className={clsx(
                          "text-xs",
                          isTerminal(job.status) && job.status !== "completed"
                            ? "text-rose-400"
                            : job.status === "completed"
                              ? "text-emerald-400"
                              : "text-amber-300"
                        )}
                      >
                        {jobStatusLabel(job.status)}
                      </span>
                    </div>
                    <p className="mt-1 line-clamp-2 text-xs text-slate-400">{job.prompt}</p>
                    {job.last_error ? <p className="mt-1 text-xs text-rose-400">{job.last_error}</p> : null}
                    {job.status === "completed" && job.video_url ? (
                      <video src={job.video_url} controls className="mt-2 max-h-48 w-full rounded bg-black" />
                    ) : null}
                    <div className="mt-2 flex flex-wrap gap-2">
                      {job.status === "completed" ? (
                        <button
                          type="button"
                          className="btn-secondary text-xs"
                          disabled={importBusy === job.id}
                          onClick={() => void importJob(job.id)}
                        >
                          {importBusy === job.id ? "…" : "В библиотеку"}
                        </button>
                      ) : null}
                      <button
                        type="button"
                        className="btn-ghost text-xs"
                        onClick={() => {
                          setModel(job.model);
                          setPrompt(job.prompt);
                          const p = job.params || {};
                          if (typeof p.duration === "string") setDuration(p.duration);
                          if (typeof p.aspect_ratio === "string") setAspect(p.aspect_ratio);
                        }}
                      >
                        Повторить
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </div>
  );
}
