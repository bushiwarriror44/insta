import { useCallback, useEffect, useMemo, useState } from "react";
import { Copy, ExternalLink, Minus, Plus, RefreshCw } from "lucide-react";

import { api, formatApiError } from "../api/client";
import type {
  FloppydataConnectionOut,
  FloppydataProtocol,
  FloppydataProxyType,
  FloppydataStatusOut,
  ProxyOut,
} from "../api/types";
import { useToast } from "../context/ToastContext";
import { copyTextToClipboard } from "./DiagnosticLogPanel";
import { EmptyState } from "./EmptyState";

type LocCountry = {
  code: string;
  name: string;
  cities: string[];
  states: string[];
};

type Subuser = { id: number; label: string };

function parseLocations(raw: unknown): LocCountry[] {
  const list = Array.isArray(raw)
    ? raw
    : raw && typeof raw === "object" && Array.isArray((raw as { items?: unknown }).items)
      ? (raw as { items: unknown[] }).items
      : raw && typeof raw === "object" && Array.isArray((raw as { countries?: unknown }).countries)
        ? (raw as { countries: unknown[] }).countries
        : [];
  const out: LocCountry[] = [];
  for (const row of list) {
    if (!row || typeof row !== "object") continue;
    const r = row as Record<string, unknown>;
    const code = String(r.code || r.countryCode || r.country || "").toUpperCase();
    if (!code || code.length !== 2) continue;
    const name = String(r.name || r.countryName || code);
    const cities = Array.isArray(r.cities) ? r.cities.map(String) : [];
    const states = Array.isArray(r.states) ? r.states.map(String) : [];
    out.push({ code, name, cities, states });
  }
  return out.sort((a, b) => a.name.localeCompare(b.name, "ru"));
}

function parseSubusers(raw: unknown): Subuser[] {
  const list = Array.isArray(raw)
    ? raw
    : raw && typeof raw === "object" && Array.isArray((raw as { items?: unknown }).items)
      ? (raw as { items: unknown[] }).items
      : [];
  const out: Subuser[] = [];
  for (const row of list) {
    if (!row || typeof row !== "object") continue;
    const r = row as Record<string, unknown>;
    const id = Number(r.id);
    if (!Number.isFinite(id) || id < 1) continue;
    const label = String(r.username || r.name || r.label || `subuser #${id}`);
    out.push({ id, label });
  }
  return out;
}

function formatGb(gb: number | null | undefined, bytes?: number | null): string {
  if (gb != null && Number.isFinite(gb)) {
    const n = Number(gb);
    if (Number.isInteger(n) || Math.abs(n - Math.round(n)) < 1e-9) {
      return `${Math.round(n)} GB`;
    }
    if (n >= 10) return `${n.toFixed(1)} GB`;
    return `${n.toFixed(2)} GB`;
  }
  if (bytes != null && Number.isFinite(bytes)) {
    const n = Number(bytes);
    if (n >= 1024 ** 3) return `${(n / 1024 ** 3).toFixed(2)} GB`;
    if (n >= 1024 ** 2) return `${(n / 1024 ** 2).toFixed(1)} MB`;
    return `${n} B`;
  }
  return "—";
}

function formatExpiringHint(status: FloppydataStatusOut): string | null {
  if (status.expiring_gb == null || status.expiring_gb <= 0) return null;
  const amt = formatGb(status.expiring_gb);
  if (!status.expiring_at) return `из них ${amt} с сроком`;
  const d = new Date(status.expiring_at);
  if (Number.isNaN(d.getTime())) return `из них ${amt} с сроком`;
  const label = d.toLocaleDateString("ru-RU", { day: "numeric", month: "short" });
  return `из них ${amt} до ${label}`;
}

export function FloppydataProxyPanel({
  onImported,
}: {
  onImported: (proxies: ProxyOut[]) => void;
}) {
  const { push } = useToast();
  const [status, setStatus] = useState<FloppydataStatusOut | null>(null);
  const [apiKeyDraft, setApiKeyDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [proxyType, setProxyType] = useState<FloppydataProxyType>("residential");
  const [protocol, setProtocol] = useState<FloppydataProtocol>("http");
  const [rotation, setRotation] = useState(0);
  const [udp, setUdp] = useState(false);
  const [country, setCountry] = useState("US");
  const [city, setCity] = useState("");
  const [state, setState] = useState("");
  const [count, setCount] = useState(1);
  const [subuserId, setSubuserId] = useState<number | "">("");
  const [locations, setLocations] = useState<LocCountry[]>([]);
  const [subusers, setSubusers] = useState<Subuser[]>([]);
  const [items, setItems] = useState<FloppydataConnectionOut[]>([]);
  const [copied, setCopied] = useState<string | null>(null);

  const selectedLoc = useMemo(
    () => locations.find((c) => c.code === country) ?? null,
    [locations, country]
  );

  const loadStatus = useCallback(async () => {
    const next = await api.floppydata.status();
    setStatus(next);
    return next;
  }, []);

  const loadMeta = useCallback(async (type: FloppydataProxyType) => {
    const [locs, subs] = await Promise.all([
      api.floppydata.locations(type),
      api.floppydata.subusers().catch(() => []),
    ]);
    const parsed = parseLocations(locs);
    setLocations(parsed);
    setSubusers(parseSubusers(subs));
    if (parsed.length && !parsed.some((c) => c.code === country)) {
      setCountry(parsed[0].code);
    }
  }, [country]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const st = await loadStatus();
        if (cancelled || !st.configured || st.error) return;
        await loadMeta(proxyType);
      } catch (err) {
        if (!cancelled) push(formatApiError(err), "error");
      }
    })();
    return () => {
      cancelled = true;
    };
    // initial only
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!status?.configured || status.error) return;
    let cancelled = false;
    (async () => {
      try {
        await loadMeta(proxyType);
      } catch (err) {
        if (!cancelled) push(formatApiError(err), "error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [proxyType]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    setCity("");
    setState("");
  }, [country]);

  const saveKey = async () => {
    setBusy(true);
    try {
      const next = await api.floppydata.setApiKey(apiKeyDraft.trim());
      setStatus(next);
      setApiKeyDraft("");
      if (next.configured && !next.error) {
        await loadMeta(proxyType);
        push("Ключ Floppydata сохранён", "success");
      } else if (next.error) {
        push(next.error, "error");
      }
    } catch (err) {
      push(formatApiError(err), "error");
    } finally {
      setBusy(false);
    }
  };

  const generate = async () => {
    setBusy(true);
    try {
      const out = await api.floppydata.generate({
        type: proxyType,
        country,
        city: state ? null : city || null,
        state: state || null,
        protocol,
        rotation,
        udp: udp && protocol === "socks5",
        subuser_id: subuserId === "" ? null : subuserId,
        count,
      });
      setItems(out.items);
      push(`Сгенерировано: ${out.items.length}`, "success");
    } catch (err) {
      push(formatApiError(err), "error");
    } finally {
      setBusy(false);
    }
  };

  const copyOne = async (value: string, id: string) => {
    const ok = await copyTextToClipboard(value);
    if (!ok) {
      push("Не удалось скопировать", "error");
      return;
    }
    setCopied(id);
    window.setTimeout(() => setCopied((cur) => (cur === id ? null : cur)), 1200);
  };

  const copyAll = async () => {
    const text = items.map((i) => i.connection_string).join("\n");
    await copyOne(text, "all");
  };

  const importToPool = async () => {
    if (!items.length) return;
    setBusy(true);
    try {
      const cc = country.toLowerCase();
      const imported = await api.floppydata.importProxies({
        run_health_check: true,
        items: items.map((row, i) => ({
          label: `floppy-${cc}-${i + 1}`,
          url: row.connection_string,
          country,
        })),
      });
      onImported(imported);
      push(`Добавлено в пул: ${imported.length}`, "success");
    } catch (err) {
      push(formatApiError(err), "error");
    } finally {
      setBusy(false);
    }
  };

  const udpAllowed =
    protocol === "socks5" && (proxyType === "residential" || proxyType === "mobile");

  const balanceLabel = status?.configured
    ? formatGb(status.balance_gb, status.balance_bytes)
    : "—";
  const expiringHint = status ? formatExpiringHint(status) : null;

  return (
    <div className="space-y-4" data-testid="floppydata-proxy-panel">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-100">Get proxy credentials</h2>
          <p className="mt-1 text-sm text-slate-400">
            Параметры как в кабинете Floppydata: сгенерируйте строки и добавьте в пул панели.
          </p>
        </div>
      </div>

      <section
        className="rounded-xl border border-slate-800 bg-gradient-to-br from-slate-900/90 to-slate-950 p-4 sm:p-5"
        aria-label="Статус Floppydata"
      >
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0 space-y-3">
            <div className="flex flex-wrap items-center gap-2">
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
            </div>
            <div>
              <p className="text-[11px] uppercase tracking-wide text-slate-500">
                Rotating traffic
              </p>
              <p
                className="mt-0.5 text-2xl font-semibold tracking-tight text-slate-100"
                data-testid="floppy-balance"
              >
                {balanceLabel}
              </p>
              {expiringHint ? (
                <p className="mt-1 text-xs text-slate-500">{expiringHint}</p>
              ) : null}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              className="btn-ghost text-xs"
              disabled={busy}
              onClick={() =>
                void loadStatus().then((next) => {
                  if (next.configured) return loadMeta(proxyType);
                })
              }
            >
              <RefreshCw className="mr-1 inline h-3.5 w-3.5" />
              Обновить
            </button>
            <a
              href="https://app.floppydata.com"
              target="_blank"
              rel="noreferrer"
              className="btn-ghost text-xs"
            >
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
            <label className="block space-y-1.5" htmlFor="floppy-api-key">
              <span className="text-[11px] uppercase tracking-wide text-slate-500">
                {status?.configured ? "Заменить API-ключ" : "API-ключ"}
              </span>
              <div className="flex flex-wrap gap-2">
                <input
                  id="floppy-api-key"
                  className="input min-w-[16rem] flex-1 font-mono text-xs"
                  type="password"
                  placeholder={status?.configured ? "••••••••••••" : "X-Api-Key Floppydata"}
                  value={apiKeyDraft}
                  onChange={(e) => setApiKeyDraft(e.target.value)}
                  autoComplete="off"
                />
                <button
                  type="button"
                  className="btn-primary text-xs"
                  disabled={busy || !apiKeyDraft.trim()}
                  onClick={() => void saveKey()}
                >
                  Сохранить
                </button>
              </div>
            </label>
          </div>
        ) : (
          <p className="mt-4 border-t border-slate-800 pt-3 text-xs text-slate-500">
            Ключ задан через FLOPPYDATA_API_KEY на сервере — смена только в окружении.
          </p>
        )}
      </section>

      {!status?.configured ? (
        <EmptyState>Сначала укажите API-ключ Floppydata.</EmptyState>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <label className="block space-y-1">
              <span className="text-[11px] uppercase tracking-wide text-slate-500">Subuser</span>
              <select
                className="input"
                value={subuserId === "" ? "" : String(subuserId)}
                onChange={(e) =>
                  setSubuserId(e.target.value ? Number(e.target.value) : "")
                }
                aria-label="Subuser"
              >
                <option value="">По умолчанию</option>
                {subusers.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="block space-y-1">
              <span className="text-[11px] uppercase tracking-wide text-slate-500">Proxy type</span>
              <select
                className="input"
                value={proxyType}
                onChange={(e) => setProxyType(e.target.value as FloppydataProxyType)}
                aria-label="Proxy type"
              >
                <option value="residential">Residential</option>
                <option value="mobile">Mobile</option>
                <option value="datacenter">Datacenter</option>
              </select>
            </label>
            <label className="block space-y-1">
              <span className="text-[11px] uppercase tracking-wide text-slate-500">Rotation</span>
              <select
                className="input"
                value={String(rotation)}
                onChange={(e) => setRotation(Number(e.target.value))}
                aria-label="Rotation"
              >
                <option value="0">Sticky (0)</option>
                <option value="-1">Every request (−1)</option>
                {[5, 10, 15, 30, 60].map((m) => (
                  <option key={m} value={m}>
                    {m} мин
                  </option>
                ))}
              </select>
            </label>
            <label className="block space-y-1">
              <span className="text-[11px] uppercase tracking-wide text-slate-500">Protocol</span>
              <select
                className="input"
                value={protocol}
                onChange={(e) => setProtocol(e.target.value as FloppydataProtocol)}
                aria-label="Protocol"
              >
                <option value="http">HTTP</option>
                <option value="https">HTTPS</option>
                <option value="socks5">SOCKS5</option>
              </select>
            </label>
            <label className="flex items-end gap-2 pb-2 text-sm text-slate-200">
              <input
                type="checkbox"
                checked={udp && udpAllowed}
                disabled={!udpAllowed}
                onChange={(e) => setUdp(e.target.checked)}
                aria-label="UDP"
              />
              UDP{" "}
              <span className="text-[10px] uppercase text-slate-500">beta</span>
            </label>
            <label className="block space-y-1">
              <span className="text-[11px] uppercase tracking-wide text-slate-500">Country</span>
              <select
                className="input"
                value={country}
                onChange={(e) => setCountry(e.target.value)}
                aria-label="Country"
              >
                {locations.length === 0 ? (
                  <option value={country}>{country}</option>
                ) : (
                  locations.map((c) => (
                    <option key={c.code} value={c.code}>
                      {c.name} ({c.code})
                    </option>
                  ))
                )}
              </select>
            </label>
            <label className="block space-y-1">
              <span className="text-[11px] uppercase tracking-wide text-slate-500">State</span>
              <select
                className="input"
                value={state}
                disabled={!selectedLoc?.states.length}
                onChange={(e) => setState(e.target.value)}
                aria-label="State"
              >
                <option value="">—</option>
                {(selectedLoc?.states ?? []).map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </label>
            <label className="block space-y-1">
              <span className="text-[11px] uppercase tracking-wide text-slate-500">City</span>
              <select
                className="input"
                value={city}
                disabled={Boolean(state) || !selectedLoc?.cities.length}
                onChange={(e) => setCity(e.target.value)}
                aria-label="City"
              >
                <option value="">—</option>
                {(selectedLoc?.cities ?? []).map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-2 rounded-lg border border-slate-700 px-2 py-1">
              <span className="text-xs text-slate-500">Число прокси</span>
              <button
                type="button"
                className="btn-ghost px-1"
                aria-label="Меньше"
                disabled={count <= 1 || busy}
                onClick={() => setCount((n) => Math.max(1, n - 1))}
              >
                <Minus className="h-3.5 w-3.5" />
              </button>
              <span className="min-w-[1.5rem] text-center text-sm text-slate-100" data-testid="floppy-count">
                {count}
              </span>
              <button
                type="button"
                className="btn-ghost px-1"
                aria-label="Больше"
                disabled={count >= 20 || busy}
                onClick={() => setCount((n) => Math.min(20, n + 1))}
              >
                <Plus className="h-3.5 w-3.5" />
              </button>
            </div>
            <button
              type="button"
              className="btn-primary text-sm"
              disabled={busy}
              onClick={() => void generate()}
            >
              Сгенерировать
            </button>
            <button
              type="button"
              className="btn-ghost text-sm"
              disabled={busy || !items.length}
              onClick={() => void importToPool()}
            >
              Добавить в пул
            </button>
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-950/80 p-3">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs font-medium text-slate-300">Proxy strings</p>
              <button
                type="button"
                className="btn-ghost text-xs"
                disabled={!items.length}
                onClick={() => void copyAll()}
              >
                <Copy className="mr-1 inline h-3.5 w-3.5" />
                {copied === "all" ? "Скопировано" : "Copy all"}
              </button>
            </div>
            {items.length === 0 ? (
              <p className="text-xs text-slate-500">Пока пусто — нажмите «Сгенерировать».</p>
            ) : (
              <ul className="max-h-64 space-y-1 overflow-y-auto" data-testid="floppy-proxy-list">
                {items.map((row, i) => (
                  <li
                    key={`${row.connection_string}-${i}`}
                    className="flex items-start gap-2 rounded-md bg-slate-900/80 px-2 py-1.5"
                  >
                    <code className="min-w-0 flex-1 break-all font-mono text-[11px] text-slate-300">
                      {row.connection_string}
                    </code>
                    <button
                      type="button"
                      className="btn-ghost shrink-0 px-1"
                      aria-label={`Копировать прокси ${i + 1}`}
                      onClick={() => void copyOne(row.connection_string, String(i))}
                    >
                      <Copy className="h-3.5 w-3.5" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </div>
  );
}
