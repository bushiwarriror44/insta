import {
  Check,
  ChevronDown,
  ChevronUp,
  Copy,
  ExternalLink,
  Loader2,
  Plus,
  RefreshCw,
  Smartphone,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api, formatApiError } from "../api/client";
import type {
  HeroSmsActiveActivationOut,
  HeroSmsHistoryItemOut,
  HeroSmsOrderOut,
  HeroSmsPriceRow,
  HeroSmsStatusOut,
} from "../api/types";
import { usePollWhenVisible } from "../hooks/usePollWhenVisible";
import { useToast } from "../context/ToastContext";
import { copyTextToClipboard } from "./DiagnosticLogPanel";
import { EmptyState } from "./EmptyState";

const LS_ACTIVATION = "insta.heroSms.lastActivationId";

const SERVICE_PRESETS: { code: string; label: string }[] = [
  { code: "ig", label: "Instagram" },
  { code: "go", label: "Google / YouTube" },
  { code: "tg", label: "Telegram" },
  { code: "lf", label: "TikTok" },
];

type CountryOption = { id: number; name: string };
type ServiceOption = { code: string; name: string };

type ActiveSession = HeroSmsOrderOut & {
  sms_code?: string | null;
  sms_text?: string | null;
};

type SmsUiState = {
  code?: string;
  text?: string;
  dateTime?: string;
  awaitingResend?: boolean;
};

function parseCountries(raw: unknown): CountryOption[] {
  const out: CountryOption[] = [];
  const push = (id: unknown, name: unknown) => {
    const n = Number(id);
    if (!Number.isFinite(n)) return;
    const label = String(name || `#${n}`).trim() || `#${n}`;
    out.push({ id: n, name: label });
  };
  if (Array.isArray(raw)) {
    for (const row of raw) {
      if (!row || typeof row !== "object") continue;
      const r = row as Record<string, unknown>;
      push(r.id ?? r.country, r.rus ?? r.eng ?? r.name ?? r.visible);
    }
  } else if (raw && typeof raw === "object") {
    for (const [key, row] of Object.entries(raw as Record<string, unknown>)) {
      if (row && typeof row === "object") {
        const r = row as Record<string, unknown>;
        push(r.id ?? key, r.rus ?? r.eng ?? r.name ?? r.visible);
      } else {
        push(key, row);
      }
    }
  }
  const seen = new Set<number>();
  return out
    .filter((c) => {
      if (seen.has(c.id)) return false;
      seen.add(c.id);
      return true;
    })
    .sort((a, b) => a.name.localeCompare(b.name, "ru"));
}

function parseServices(raw: unknown): ServiceOption[] {
  const out: ServiceOption[] = [];
  const list = Array.isArray(raw)
    ? raw
    : raw && typeof raw === "object" && Array.isArray((raw as { services?: unknown }).services)
      ? (raw as { services: unknown[] }).services
      : raw && typeof raw === "object"
        ? Object.entries(raw as Record<string, unknown>).map(([code, v]) => {
            if (v && typeof v === "object") {
              const row = v as Record<string, unknown>;
              return { code, name: row.name ?? row.ru ?? code };
            }
            return { code, name: String(v ?? code) };
          })
        : [];
  for (const row of list) {
    if (!row || typeof row !== "object") continue;
    const r = row as Record<string, unknown>;
    const code = String(r.code ?? r.service ?? r.id ?? "").trim();
    if (!code) continue;
    const name = String(r.name ?? r.ru ?? r.eng ?? code);
    out.push({ code, name });
  }
  return out.sort((a, b) => a.name.localeCompare(b.name, "ru"));
}

function formatMoney(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—";
  return n < 0.1 ? `$${n.toFixed(4)}` : `$${n.toFixed(3)}`;
}

function parseEndMs(end: string | null | undefined): number | null {
  if (!end) return null;
  const d = new Date(end.replace(" ", "T"));
  return Number.isNaN(d.getTime()) ? null : d.getTime();
}

function Countdown({ endTime }: { endTime: string | null | undefined }) {
  const endMs = parseEndMs(endTime);
  const [left, setLeft] = useState<number | null>(null);
  useEffect(() => {
    if (endMs == null) {
      setLeft(null);
      return;
    }
    const tick = () => setLeft(Math.max(0, Math.floor((endMs - Date.now()) / 1000)));
    tick();
    const id = window.setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [endMs]);
  if (left == null) return <span className="text-slate-500">—</span>;
  const m = Math.floor(left / 60);
  const s = left % 60;
  return (
    <span className="font-mono text-amber-200">
      {m}:{s.toString().padStart(2, "0")}
    </span>
  );
}

function activationFromActive(row: HeroSmsActiveActivationOut): ActiveSession {
  return {
    activation_id: row.activation_id,
    phone_number: row.phone_number,
    phone_e164: row.phone_e164,
    activation_cost: row.activation_cost,
    country_id: row.country_id,
    service_code: row.service_code,
    activation_time: row.activation_time,
    activation_end_time: null,
    can_get_another_sms: true,
    sms_code: row.sms_code,
    sms_text: row.sms_text,
  };
}

function mergeSession(prev: ActiveSession, next: ActiveSession): ActiveSession {
  return {
    ...prev,
    ...next,
    activation_end_time: next.activation_end_time ?? prev.activation_end_time,
  };
}

function WizardStepPill({ step, current, label }: { step: number; current: number; label: string }) {
  const active = current === step;
  const done = current > step;
  return (
    <div
      className={`flex items-center gap-2 rounded-lg px-3 py-1.5 text-xs ${
        active
          ? "bg-brand-500/15 text-brand-200 ring-1 ring-brand-500/40"
          : done
            ? "text-emerald-400/90"
            : "text-slate-500"
      }`}
      data-testid={`hero-wizard-step-${step}`}
    >
      <span
        className={`flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-semibold ${
          active ? "bg-brand-500 text-slate-950" : done ? "bg-emerald-500/20 text-emerald-300" : "bg-slate-800"
        }`}
      >
        {done ? "✓" : step}
      </span>
      {label}
    </div>
  );
}

export function HeroSmsPanel() {
  const { push } = useToast();
  const navigate = useNavigate();
  const [status, setStatus] = useState<HeroSmsStatusOut | null>(null);
  const [apiKeyDraft, setApiKeyDraft] = useState("");
  const [statusBusy, setStatusBusy] = useState(false);
  const [countries, setCountries] = useState<CountryOption[]>([]);
  const [services, setServices] = useState<ServiceOption[]>([]);
  const [service, setService] = useState("ig");
  const [serviceQuery, setServiceQuery] = useState("");
  const [countryId, setCountryId] = useState<number | null>(null);
  const [countryQuery, setCountryQuery] = useState("");
  const [inStockOnly, setInStockOnly] = useState(true);
  const [priceRows, setPriceRows] = useState<HeroSmsPriceRow[]>([]);
  const [pricesLoading, setPricesLoading] = useState(false);
  const [strictPrice, setStrictPrice] = useState(false);
  const [orderBusy, setOrderBusy] = useState(false);
  const [activeList, setActiveList] = useState<ActiveSession[]>([]);
  const [detailFocusId, setDetailFocusId] = useState<string | null>(null);
  const [smsById, setSmsById] = useState<Record<string, SmsUiState>>({});
  const [codeFlashId, setCodeFlashId] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState<HeroSmsHistoryItemOut[]>([]);
  const [actionBusy, setActionBusy] = useState(false);
  const [statusPollBusy, setStatusPollBusy] = useState(false);

  const lastSmsDtRef = useRef<Record<string, string>>({});
  const awaitingResendRef = useRef<Record<string, boolean>>({});
  const wizardFocusRef = useRef(false);

  const wizardStep = countryId != null ? 3 : 2;

  const refreshStatus = useCallback(async () => {
    setStatusBusy(true);
    try {
      const next = await api.heroSms.status();
      setStatus(next);
      if (next.last_form?.service) setService(next.last_form.service);
      if (next.last_form?.country_id != null) setCountryId(next.last_form.country_id);
      if (next.last_form?.strict_price) setStrictPrice(true);
      return next;
    } catch (err) {
      push(formatApiError(err), "error");
      return null;
    } finally {
      setStatusBusy(false);
    }
  }, [push]);

  const seedSmsFromSessions = useCallback((sessions: ActiveSession[]) => {
    setSmsById((prev) => {
      const next = { ...prev };
      for (const s of sessions) {
        if (s.sms_code && !next[s.activation_id]?.awaitingResend) {
          next[s.activation_id] = {
            code: s.sms_code,
            text: s.sms_text || undefined,
            dateTime: next[s.activation_id]?.dateTime,
          };
        }
      }
      return next;
    });
  }, []);

  const refreshActiveList = useCallback(async () => {
    if (!status?.configured) return;
    try {
      const { items } = await api.heroSms.active();
      const mapped = items.map(activationFromActive);
      setActiveList((prev) => {
        const byId = new Map(prev.map((p) => [p.activation_id, p]));
        return mapped.map((m) => mergeSession(byId.get(m.activation_id) ?? m, m));
      });
      seedSmsFromSessions(mapped);
      if (wizardFocusRef.current) return;
      const savedId = localStorage.getItem(LS_ACTIVATION);
      const pick =
        mapped.find((i) => i.activation_id === savedId) ?? mapped[0];
      if (pick) {
        setDetailFocusId((cur) => cur ?? pick.activation_id);
        localStorage.setItem(LS_ACTIVATION, pick.activation_id);
      }
    } catch {
      // optional
    }
  }, [status?.configured, seedSmsFromSessions]);

  const loadMeta = useCallback(async () => {
    if (!status?.configured) return;
    try {
      const [c, s] = await Promise.all([api.heroSms.countries(), api.heroSms.services()]);
      setCountries(parseCountries(c));
      setServices(parseServices(s));
    } catch (err) {
      push(formatApiError(err), "error");
    }
  }, [status?.configured, push]);

  const loadPrices = useCallback(async () => {
    if (!status?.configured || !service) return;
    setPricesLoading(true);
    try {
      const out = await api.heroSms.prices(service);
      setPriceRows(out.rows || []);
    } catch (err) {
      push(formatApiError(err), "error");
      setPriceRows([]);
    } finally {
      setPricesLoading(false);
    }
  }, [status?.configured, service, push]);

  useEffect(() => {
    void refreshStatus();
  }, [refreshStatus]);

  useEffect(() => {
    void loadMeta();
  }, [loadMeta]);

  useEffect(() => {
    void loadPrices();
  }, [loadPrices]);

  useEffect(() => {
    void refreshActiveList();
  }, [refreshActiveList]);

  const selectedPrice = useMemo(
    () => priceRows.find((r) => r.country_id === countryId) ?? null,
    [priceRows, countryId]
  );

  const countryName = useCallback(
    (id: number) => countries.find((c) => c.id === id)?.name ?? `#${id}`,
    [countries]
  );

  const filteredServices = useMemo(() => {
    const q = serviceQuery.trim().toLowerCase();
    if (!q) return services.slice(0, 80);
    return services.filter((s) => s.code.includes(q) || s.name.toLowerCase().includes(q)).slice(0, 80);
  }, [services, serviceQuery]);

  const filteredPriceRows = useMemo(() => {
    const q = countryQuery.trim().toLowerCase();
    let rows = priceRows;
    if (inStockOnly) rows = rows.filter((r) => (r.count ?? 0) > 0);
    if (q) {
      rows = rows.filter(
        (r) =>
          countryName(r.country_id).toLowerCase().includes(q) ||
          String(r.country_id).includes(q)
      );
    }
    return rows.slice(0, 120);
  }, [priceRows, countryQuery, countryName, inStockOnly]);

  const detailSession = useMemo(
    () => activeList.find((a) => a.activation_id === detailFocusId) ?? null,
    [activeList, detailFocusId]
  );

  const pollActivation = useCallback(async () => {
    if (!detailFocusId) return;
    try {
      const st = await api.heroSms.activationStatus(detailFocusId);
      const sms = st.sms;
      if (!sms?.code && !sms?.text) return;
      const dt = sms.date_time?.trim() ?? "";
      const prev = lastSmsDtRef.current[detailFocusId];
      const awaiting = awaitingResendRef.current[detailFocusId];
      if (awaiting && prev && dt && dt === prev) return;
      if (!awaiting && prev && dt && dt === prev) return;

      const code = sms.code ?? undefined;
      const text = sms.text ?? undefined;
      const isNew = Boolean(code) && (!prev || (dt && dt !== prev) || awaiting);

      if (dt) lastSmsDtRef.current[detailFocusId] = dt;
      awaitingResendRef.current[detailFocusId] = false;

      setSmsById((s) => ({
        ...s,
        [detailFocusId]: { code, text, dateTime: dt || undefined, awaitingResend: false },
      }));

      if (isNew && code) {
        push("Код получен", "success");
        setCodeFlashId(detailFocusId);
        window.setTimeout(() => setCodeFlashId((id) => (id === detailFocusId ? null : id)), 2200);
      }
    } catch {
      // transient
    }
  }, [detailFocusId, push]);

  usePollWhenVisible(pollActivation, 3000, Boolean(detailFocusId && status?.configured));

  async function saveApiKey() {
    const trimmed = apiKeyDraft.trim();
    if (!trimmed) {
      push("Введите API-ключ", "error");
      return;
    }
    try {
      const next = await api.heroSms.setApiKey(trimmed);
      setStatus(next);
      setApiKeyDraft("");
      push("Ключ Hero SMS сохранён", "success");
      void loadMeta();
      void refreshActiveList();
    } catch (err) {
      push(formatApiError(err), "error");
    }
  }

  async function placeOrder() {
    if (countryId == null) {
      push("Выберите страну", "error");
      return;
    }
    if ((selectedPrice?.count ?? 0) <= 0) {
      push("Нет номеров в наличии для этой страны", "error");
      return;
    }
    setOrderBusy(true);
    try {
      const body = {
        service,
        country_id: countryId,
        strict_price: strictPrice,
        max_price: strictPrice && selectedPrice?.cost != null ? selectedPrice.cost : undefined,
      };
      const order = await api.heroSms.order(body);
      setActiveList((prev) => {
        const idx = prev.findIndex((p) => p.activation_id === order.activation_id);
        if (idx >= 0) {
          const copy = [...prev];
          copy[idx] = mergeSession(copy[idx], order);
          return copy;
        }
        return [...prev, order];
      });
      wizardFocusRef.current = false;
      setDetailFocusId(order.activation_id);
      localStorage.setItem(LS_ACTIVATION, order.activation_id);
      setSmsById((s) => ({ ...s, [order.activation_id]: { awaitingResend: true } }));
      awaitingResendRef.current[order.activation_id] = true;
      delete lastSmsDtRef.current[order.activation_id];
      push("Номер получен — ждём SMS", "success");
      void refreshStatus();
      void refreshActiveList();
    } catch (err) {
      push(formatApiError(err), "error");
    } finally {
      setOrderBusy(false);
    }
  }

  async function runAction(statusCode: 3 | 6 | 8) {
    if (!detailFocusId) return;
    const id = detailFocusId;
    setActionBusy(true);
    try {
      await api.heroSms.activationAction(id, statusCode);
      if (statusCode === 8) {
        setActiveList((list) => list.filter((a) => a.activation_id !== id));
        setDetailFocusId((cur) => (cur === id ? null : cur));
        localStorage.removeItem(LS_ACTIVATION);
        push("Активация отменена", "success");
      } else if (statusCode === 6) {
        setActiveList((list) => list.filter((a) => a.activation_id !== id));
        setDetailFocusId((cur) => (cur === id ? null : cur));
        localStorage.removeItem(LS_ACTIVATION);
        push("Активация завершена", "success");
      } else {
        awaitingResendRef.current[id] = true;
        setSmsById((s) => ({
          ...s,
          [id]: { ...s[id], code: undefined, text: undefined, awaitingResend: true },
        }));
        push("Запрошена повторная SMS", "success");
      }
      void refreshStatus();
      void refreshActiveList();
    } catch (err) {
      push(formatApiError(err), "error");
    } finally {
      setActionBusy(false);
    }
  }

  async function manualStatusRefresh() {
    if (!detailFocusId) return;
    setStatusPollBusy(true);
    try {
      await pollActivation();
    } finally {
      setStatusPollBusy(false);
    }
  }

  async function loadHistory() {
    try {
      const out = await api.heroSms.history(15);
      setHistory(out.items);
    } catch (err) {
      push(formatApiError(err), "error");
    }
  }

  useEffect(() => {
    if (historyOpen) void loadHistory();
  }, [historyOpen]);

  const displaySms = detailFocusId ? smsById[detailFocusId] : undefined;
  const displayCode =
    displaySms?.awaitingResend ? undefined : displaySms?.code ?? detailSession?.sms_code ?? undefined;
  const displayText =
    displaySms?.awaitingResend ? undefined : displaySms?.text ?? detailSession?.sms_text ?? undefined;
  const waitingSms = Boolean(detailFocusId && !displayCode);

  async function copyPhone(phone: string) {
    const ok = await copyTextToClipboard(phone);
    push(ok ? "Номер скопирован" : "Не удалось скопировать", ok ? "success" : "error");
  }

  async function copyCode() {
    if (!displayCode) return;
    const ok = await copyTextToClipboard(displayCode);
    push(ok ? "Код скопирован" : "Не удалось скопировать", ok ? "success" : "error");
  }

  async function copySmsText() {
    if (!displayText) return;
    const ok = await copyTextToClipboard(displayText);
    push(ok ? "Текст SMS скопирован" : "Не удалось скопировать", ok ? "success" : "error");
  }

  const balanceLabel =
    status?.balance != null && Number.isFinite(status.balance) ? formatMoney(status.balance) : "—";

  return (
    <div className="space-y-4" data-testid="hero-sms-panel">
      <section
        className="rounded-xl border border-slate-800 bg-gradient-to-br from-slate-900/90 to-slate-950 p-4 sm:p-5"
        aria-label="Подключение Hero SMS"
      >
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0 space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <Smartphone size={18} className="text-brand-400" aria-hidden />
              <span
                className={
                  status?.configured
                    ? "inline-flex items-center rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-xs font-medium text-emerald-300"
                    : "inline-flex items-center rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-xs font-medium text-amber-300"
                }
              >
                {status?.configured
                  ? status.key_from_env
                    ? "Ключ из env"
                    : "Ключ сохранён"
                  : "Ключ не задан"}
              </span>
              <a
                href="https://hero-sms.com/"
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-xs text-brand-400 hover:underline"
              >
                hero-sms.com <ExternalLink size={12} />
              </a>
            </div>
            <div>
              <p className="text-[11px] uppercase tracking-wide text-slate-500">Баланс</p>
              <p
                className="mt-0.5 text-2xl font-semibold tracking-tight text-slate-100"
                data-testid="hero-sms-balance"
              >
                {balanceLabel}
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              className="btn-ghost text-xs"
              disabled={statusBusy}
              onClick={() =>
                void refreshStatus().then((n) => {
                  if (n?.configured) void loadMeta();
                })
              }
            >
              <RefreshCw className={`mr-1 inline h-3.5 w-3.5 ${statusBusy ? "animate-spin" : ""}`} />
              Обновить
            </button>
            <a href="https://hero-sms.com/" target="_blank" rel="noreferrer" className="btn-ghost text-xs">
              <ExternalLink className="mr-1 inline h-3.5 w-3.5" />
              Пополнить
            </a>
          </div>
        </div>

        {status?.error ? (
          <p className="mt-3 rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
            {status.error}
          </p>
        ) : null}

        {!status?.key_from_env ? (
          <div className="mt-4 border-t border-slate-800 pt-4">
            <label className="block space-y-1.5" htmlFor="hero-sms-api-key">
              <span className="text-[11px] uppercase tracking-wide text-slate-500">
                {status?.configured ? "Заменить API-ключ" : "API-ключ"}
              </span>
              <div className="flex flex-wrap gap-2">
                <input
                  id="hero-sms-api-key"
                  className="input min-w-[16rem] flex-1 font-mono text-xs"
                  type="password"
                  placeholder={status?.configured ? "••••••••••••" : "Ключ из кабинета Hero SMS"}
                  value={apiKeyDraft}
                  onChange={(e) => setApiKeyDraft(e.target.value)}
                  autoComplete="off"
                />
                <button
                  type="button"
                  className="btn-primary text-xs"
                  disabled={statusBusy || !apiKeyDraft.trim()}
                  onClick={() => void saveApiKey()}
                >
                  Сохранить
                </button>
              </div>
            </label>
          </div>
        ) : (
          <p className="mt-4 border-t border-slate-800 pt-3 text-xs text-slate-500">
            Ключ задан через HERO_SMS_API_KEY на сервере — смена только в окружении.
          </p>
        )}
      </section>

      {!status?.configured ? (
        <EmptyState>Вставьте API-ключ Hero SMS в поле выше, чтобы покупать номера.</EmptyState>
      ) : (
        <>
          {activeList.length > 0 ? (
            <section className="card p-4 space-y-3" aria-label="Активные номера">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-sm font-medium text-slate-200">Активные номера</h3>
                <button
                  type="button"
                  className="btn-ghost btn-compact text-xs"
                  onClick={() => {
                    wizardFocusRef.current = true;
                    setDetailFocusId(null);
                  }}
                >
                  <Plus size={14} /> Новая покупка
                </button>
              </div>
              <div className="flex flex-wrap gap-2">
                {activeList.map((a) => (
                  <button
                    key={a.activation_id}
                    type="button"
                    className={
                      detailFocusId === a.activation_id
                        ? "rounded-lg border border-brand-500/50 bg-brand-500/10 px-3 py-1.5 text-xs text-brand-200"
                        : "rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-1.5 text-xs text-slate-400 hover:border-slate-700"
                    }
                    onClick={() => {
                      wizardFocusRef.current = false;
                      setDetailFocusId(a.activation_id);
                      localStorage.setItem(LS_ACTIVATION, a.activation_id);
                    }}
                  >
                    <span className="font-mono">{a.phone_e164 || a.phone_number}</span>
                    {a.service_code ? (
                      <span className="ml-2 text-slate-500">{a.service_code}</span>
                    ) : null}
                  </button>
                ))}
              </div>

              {detailFocusId && detailSession ? (
                <div
                  className={`mt-2 space-y-4 rounded-lg border p-5 ${
                    codeFlashId === detailFocusId
                      ? "border-emerald-400/60 bg-emerald-500/5 animate-pulse"
                      : "border-brand-500/30 bg-slate-950/40"
                  }`}
                  data-testid="hero-active-detail"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
                    <span>id {detailSession.activation_id}</span>
                    <span>
                      До конца: <Countdown endTime={detailSession.activation_end_time} />
                    </span>
                  </div>
                  <div className="flex flex-wrap items-baseline gap-3">
                    <span className="text-3xl font-semibold tracking-wide text-slate-50">
                      {detailSession.phone_e164 || detailSession.phone_number}
                    </span>
                    <button
                      type="button"
                      className="btn-ghost btn-compact"
                      onClick={() =>
                        void copyPhone(detailSession.phone_e164 || detailSession.phone_number)
                      }
                    >
                      <Copy size={14} /> Номер
                    </button>
                  </div>
                  {detailSession.activation_cost != null ? (
                    <p className="text-sm text-slate-400">
                      Стоимость: {formatMoney(detailSession.activation_cost)}
                    </p>
                  ) : null}
                  <div className="rounded-lg bg-slate-950/80 p-4 min-h-[5rem] flex flex-col items-center justify-center gap-2">
                    {displayCode ? (
                      <>
                        <div className="text-4xl font-mono font-bold text-emerald-300 tracking-widest">
                          {displayCode}
                        </div>
                        {displayText ? (
                          <p className="text-xs text-slate-400 text-center max-w-lg">{displayText}</p>
                        ) : null}
                        <div className="flex flex-wrap gap-2">
                          <button type="button" className="btn-ghost btn-compact" onClick={() => void copyCode()}>
                            <Copy size={14} /> Код
                          </button>
                          {displayText ? (
                            <button
                              type="button"
                              className="btn-ghost btn-compact"
                              onClick={() => void copySmsText()}
                            >
                              <Copy size={14} /> Текст SMS
                            </button>
                          ) : null}
                        </div>
                      </>
                    ) : (
                      <div className="flex items-center gap-2 text-slate-400">
                        {waitingSms ? <Loader2 size={18} className="animate-spin" /> : null}
                        Ожидание SMS…
                      </div>
                    )}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      className="btn-ghost btn-compact"
                      disabled={statusPollBusy}
                      onClick={() => void manualStatusRefresh()}
                    >
                      <RefreshCw size={14} className={statusPollBusy ? "animate-spin" : ""} />
                      Обновить статус
                    </button>
                    <button
                      type="button"
                      className="btn-ghost"
                      disabled={actionBusy}
                      onClick={() => void runAction(3)}
                    >
                      Ещё SMS
                    </button>
                    <button
                      type="button"
                      className="btn-primary"
                      disabled={actionBusy}
                      onClick={() => void runAction(6)}
                    >
                      <Check size={14} /> Готово
                    </button>
                    <button
                      type="button"
                      className="btn-ghost text-rose-300"
                      disabled={actionBusy}
                      onClick={() => void runAction(8)}
                    >
                      Отменить
                    </button>
                    <button
                      type="button"
                      className="btn-ghost"
                      onClick={() =>
                        navigate(
                          `/accounts?phone=${encodeURIComponent(detailSession.phone_e164 || detailSession.phone_number)}`
                        )
                      }
                    >
                      В новый аккаунт
                    </button>
                  </div>
                </div>
              ) : null}
            </section>
          ) : null}

          <section className="space-y-4" aria-label="Покупка номера" data-testid="hero-buy-wizard">
            <div className="flex flex-wrap gap-2">
              <WizardStepPill step={1} current={wizardStep} label="Сервис" />
              <WizardStepPill step={2} current={wizardStep} label="Страна" />
              <WizardStepPill step={3} current={wizardStep} label="Покупка" />
            </div>

            {countryId != null && selectedPrice ? (
              <div className="sticky top-2 z-10 rounded-lg border border-slate-700 bg-slate-900/95 px-3 py-2 text-sm text-slate-200 shadow-lg backdrop-blur">
                Выбрано:{" "}
                <span className="font-mono text-brand-300">{service}</span>
                {" · "}
                {countryName(countryId)}
                {" · "}
                {formatMoney(selectedPrice.cost)}
                {" · "}
                <span className={selectedPrice.count > 0 ? "text-emerald-300" : "text-rose-300"}>
                  {selectedPrice.count} шт.
                </span>
              </div>
            ) : null}

            <div className="grid gap-4 lg:grid-cols-2">
              <div className="card p-4 space-y-3">
                <h3 className="text-sm font-medium text-slate-200">1. Сервис</h3>
                <div className="flex flex-wrap gap-2">
                  {SERVICE_PRESETS.map((p) => (
                    <button
                      key={p.code}
                      type="button"
                      className={service === p.code ? "btn-primary btn-compact" : "btn-ghost btn-compact"}
                      onClick={() => {
                        setService(p.code);
                        setCountryId(null);
                      }}
                    >
                      {p.label}
                    </button>
                  ))}
                </div>
                <input
                  className="input w-full"
                  placeholder="Поиск сервиса или код (ig, go…)"
                  value={serviceQuery}
                  onChange={(e) => setServiceQuery(e.target.value)}
                />
                <div className="max-h-36 overflow-y-auto rounded border border-slate-800">
                  {filteredServices.length === 0 ? (
                    <EmptyState compact title="Нет сервисов">
                      Попробуйте другой запрос
                    </EmptyState>
                  ) : (
                    <ul className="divide-y divide-slate-800 text-xs">
                      {filteredServices.map((s) => (
                        <li key={s.code}>
                          <button
                            type="button"
                            className={`w-full px-3 py-2 text-left hover:bg-slate-900 ${
                              service === s.code ? "bg-slate-900 text-brand-300" : "text-slate-300"
                            }`}
                            onClick={() => {
                              setService(s.code);
                              setCountryId(null);
                            }}
                          >
                            <span className="font-mono text-slate-500">{s.code}</span> — {s.name}
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                <p className="text-xs text-slate-500">
                  Выбран: <span className="font-mono text-slate-300">{service}</span>
                </p>
              </div>

              <div className="card p-4 space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="text-sm font-medium text-slate-200">2. Страна и цена</h3>
                  {pricesLoading ? <Loader2 size={16} className="animate-spin text-slate-500" /> : null}
                </div>
                <div className="flex flex-wrap items-center gap-3">
                  <input
                    className="input min-w-0 flex-1"
                    placeholder="Фильтр по стране"
                    value={countryQuery}
                    onChange={(e) => setCountryQuery(e.target.value)}
                  />
                  <label className="flex shrink-0 items-center gap-2 text-xs text-slate-400">
                    <input
                      type="checkbox"
                      checked={inStockOnly}
                      onChange={(e) => setInStockOnly(e.target.checked)}
                    />
                    Только в наличии
                  </label>
                </div>
                <div className="max-h-64 overflow-y-auto rounded border border-slate-800">
                  <table className="w-full text-xs">
                    <thead className="sticky top-0 bg-slate-950 text-slate-500">
                      <tr>
                        <th className="px-2 py-1 text-left font-normal">Страна</th>
                        <th className="px-2 py-1 text-right font-normal">Цена</th>
                        <th className="px-2 py-1 text-right font-normal">шт.</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredPriceRows.map((row) => {
                        const selected = countryId === row.country_id;
                        const empty = (row.count ?? 0) <= 0;
                        return (
                          <tr
                            key={row.country_id}
                            className={`cursor-pointer border-t border-slate-900 ${
                              selected ? "bg-brand-500/10 ring-1 ring-inset ring-brand-500/30" : "hover:bg-slate-900/60"
                            } ${empty ? "opacity-45" : ""}`}
                            onClick={() => setCountryId(row.country_id)}
                          >
                            <td className="px-2 py-1.5 text-slate-300">{countryName(row.country_id)}</td>
                            <td className="px-2 py-1.5 text-right font-mono text-slate-400">
                              {formatMoney(row.cost)}
                            </td>
                            <td className="px-2 py-1.5 text-right text-slate-400">{row.count}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>

                <h3 className="text-sm font-medium text-slate-200 pt-1">3. Покупка</h3>
                <label className="flex items-center gap-2 text-xs text-slate-400">
                  <input
                    type="checkbox"
                    checked={strictPrice}
                    onChange={(e) => setStrictPrice(e.target.checked)}
                  />
                  Строгий лимит цены (не дороже выбранной)
                </label>
                <button
                  type="button"
                  className="btn-primary w-full"
                  disabled={orderBusy || countryId == null || (selectedPrice?.count ?? 0) <= 0}
                  onClick={() => void placeOrder()}
                >
                  {orderBusy ? <Loader2 size={16} className="animate-spin" /> : null}
                  Получить номер
                </button>
              </div>
            </div>
          </section>

          <div className="card p-3">
            <button
              type="button"
              className="flex w-full items-center justify-between text-sm text-slate-300"
              onClick={() => setHistoryOpen((v) => !v)}
            >
              История активаций
              {historyOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
            </button>
            {historyOpen ? (
              <ul className="mt-3 space-y-2 text-xs text-slate-400 max-h-48 overflow-y-auto">
                {history.length === 0 ? (
                  <li className="text-slate-600">Нет записей за неделю</li>
                ) : (
                  history.map((h) => (
                    <li key={h.id} className="border-t border-slate-900 pt-2">
                      <span className="text-slate-500">{h.date || h.id}</span> · {h.phone || "—"}{" "}
                      {h.sms ? `· ${h.sms.slice(0, 80)}` : ""}
                    </li>
                  ))
                )}
              </ul>
            ) : null}
          </div>
        </>
      )}

      <p className="text-xs text-slate-600">
        API:{" "}
        <Link to="/administration#api" className="text-brand-400 hover:underline">
          документация панели
        </Link>
        {" · "}
        <a
          href="https://hero-sms.com/api"
          className="text-brand-400 hover:underline"
          target="_blank"
          rel="noreferrer"
        >
          Hero SMS
        </a>
      </p>
    </div>
  );
}
