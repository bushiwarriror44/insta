import {
  CheckCircle2,
  Copy,
  ExternalLink,
  KeyRound,
  Network,
  Pencil,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Server,
  ShieldOff,
  Trash2,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import { Card } from "../components/Card";
import { CountryFlag, countryCodeToFlag } from "../components/CountryFlag";
import { DiagnosticLogPanel } from "../components/DiagnosticLogPanel";
import { Loader } from "../components/Loader";
import { Modal } from "../components/Modal";
import { StatusBadge } from "../components/StatusBadge";
import { useToast } from "../context/ToastContext";
import type {
  AccountConnectionTestOut,
  AccountIn,
  AccountOut,
  AccountProxyUpdate,
  AccountSessionOut,
  AccountSessionUpdate,
  DiagnosticRunOut,
  ProxyIn,
  ProxyOut,
  ProxyUpdate,
} from "../api/types";
import { CAPTION_PROFILE_OPTIONS } from "../api/types";

const POLL_INTERVAL_MS = 10000;

function proxyOptionLabel(p: ProxyOut): string {
  const flag = countryCodeToFlag(p.country);
  const prefix = flag ? `${flag} ` : "";
  return `${prefix}${p.label}${p.country ? ` (${p.country})` : ""}`;
}

function sessionSourceLabel(source: AccountOut["session_source"]): string {
  if (source === "database") return "DB sessionid";
  if (source === "session_file") return "Cookies file";
  return "No session";
}

type StepVisual = "pending" | "running" | "ok" | "warn" | "fail";

function ConnectionStepRow({
  label,
  state,
  detail,
}: {
  label: string;
  state: StepVisual;
  detail?: React.ReactNode;
}) {
  const dot =
    state === "ok"
      ? "bg-emerald-500"
      : state === "warn"
        ? "bg-amber-400"
        : state === "fail"
          ? "bg-rose-500"
          : state === "running"
            ? "bg-brand-400 animate-pulse"
            : "bg-slate-600";
  return (
    <div className="flex gap-3 items-start rounded-lg border border-slate-800 bg-slate-950/40 p-3">
      <span className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${dot}`} />
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium text-slate-200">{label}</div>
        {detail ? <div className="mt-1 text-xs text-slate-400">{detail}</div> : null}
      </div>
    </div>
  );
}

export function Accounts() {
  const { push } = useToast();
  const [accounts, setAccounts] = useState<AccountOut[]>([]);
  const [proxies, setProxies] = useState<ProxyOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [openAccount, setOpenAccount] = useState(false);
  const [openProxy, setOpenProxy] = useState(false);
  const [editingProxy, setEditingProxy] = useState<ProxyOut | null>(null);
  const [assigningAccount, setAssigningAccount] = useState<AccountOut | null>(null);
  const [sessionAccount, setSessionAccount] = useState<AccountOut | null>(null);
  const [connectionAccount, setConnectionAccount] = useState<AccountOut | null>(null);
  const [testingAll, setTestingAll] = useState(false);
  const [testAllProgress, setTestAllProgress] = useState({ done: 0, total: 0, ok: 0 });

  const reload = useCallback(async () => {
    const [a, p] = await Promise.all([api.accounts.list(), api.proxies.list()]);
    setAccounts(a);
    setProxies(p);
  }, []);

  useEffect(() => {
    let cancelled = false;
    let initial = true;
    async function tick() {
      try {
        await reload();
      } catch (err) {
        if (initial) push((err as Error).message, "error");
      } finally {
        if (initial) setLoading(false);
        initial = false;
      }
      if (cancelled) return;
    }
    tick();
    const id = window.setInterval(tick, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [reload, push]);

  const onCreatedAccount = async () => {
    setOpenAccount(false);
    await reload();
    push("Account saved", "success");
  };
  const onCreatedProxy = async () => {
    setOpenProxy(false);
    await reload();
    push("Proxy saved", "success");
  };
  const onUpdatedProxy = async () => {
    setEditingProxy(null);
    await reload();
    push("Proxy updated", "success");
  };
  const onAssignedProxy = async () => {
    setAssigningAccount(null);
    await reload();
    push("Account proxy updated", "success");
  };
  const onImportedSession = async () => {
    setSessionAccount(null);
    await reload();
    push("Session saved", "success");
  };

  const testAllConnections = useCallback(async () => {
    const targets = accounts.filter((a) => a.proxy_label);
    if (targets.length === 0) {
      push("No accounts with proxies to test", "error");
      return;
    }
    setTestingAll(true);
    setTestAllProgress({ done: 0, total: targets.length, ok: 0 });
    let okCount = 0;
    try {
      for (let i = 0; i < targets.length; i++) {
        const account = targets[i];
        try {
          const result = await api.accounts.testConnection(account.username);
          if (result.overall_ok) okCount += 1;
          if (result.proxy_label) {
            const label = result.proxy_label;
            setProxies((arr) =>
              arr.map((x) =>
                x.label === label
                  ? {
                      ...x,
                      is_healthy: result.proxy_health.ok,
                      last_known_ip: result.proxy_health.ip ?? x.last_known_ip,
                      last_geo_country:
                        result.proxy_health.geo_country ?? x.last_geo_country,
                      instagram_reachable: result.proxy_health.instagram_reachable,
                      geo_mismatch_warning: result.proxy_health.geo_mismatch,
                    }
                  : x
              )
            );
          }
          setAccounts((arr) =>
            arr.map((x) =>
              x.id === account.id
                ? {
                    ...x,
                    proxy_is_healthy: result.proxy_health.ok,
                    proxy_geo_country:
                      result.proxy_health.geo_country ?? x.proxy_geo_country,
                    proxy_last_ip: result.proxy_health.ip ?? x.proxy_last_ip,
                    session_file_exists: result.session_storage.session_file_exists,
                    session_source: result.session_storage.session_source,
                  }
                : x
            )
          );
        } catch (err) {
          push(`@${account.username}: ${(err as Error).message}`, "error");
        }
        setTestAllProgress({ done: i + 1, total: targets.length, ok: okCount });
      }
      push(
        `Checked ${targets.length} account(s): ${okCount} ready for autoposting`,
        okCount === targets.length ? "success" : "info"
      );
    } finally {
      setTestingAll(false);
    }
  }, [accounts, push]);

  if (loading) return <Loader />;

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold">Accounts</h1>
          <p className="text-sm text-slate-400 mt-1">
            Manage Instagram accounts and their proxies.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button className="btn-ghost" onClick={() => setOpenProxy(true)}>
            <Server size={16} />
            <span>Add proxy</span>
          </button>
          <button className="btn-primary" onClick={() => setOpenAccount(true)}>
            <Plus size={16} />
            <span>Add account</span>
          </button>
        </div>
      </div>

      <Card
        title="Proxies"
        description={`${proxies.length} configured`}
        actions={
          <button
            className="btn-ghost text-xs"
            onClick={async () => {
              try {
                await reload();
                push("Refreshed", "info");
              } catch (err) {
                push((err as Error).message, "error");
              }
            }}
          >
            <RefreshCw size={14} />
            Refresh
          </button>
        }
      >
        {proxies.length === 0 ? (
          <div className="text-sm text-slate-500">No proxies yet.</div>
        ) : (
          <div className="overflow-x-auto -mx-5">
            <table className="table-base">
              <thead>
                <tr>
                  <th>Label</th>
                  <th>URL</th>
                  <th>Country / TZ</th>
                  <th>Accounts</th>
                  <th>Last IP</th>
                  <th>Geo (actual)</th>
                  <th>Status</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {proxies.map((p) => (
                  <tr key={p.id} className="hover:bg-slate-900/40">
                    <td className="font-medium">{p.label}</td>
                    <td
                      className="max-w-[18rem] truncate font-mono text-xs text-slate-400"
                      title={p.url}
                    >
                      {p.url}
                    </td>
                    <td className="text-slate-400">
                      <span className="inline-flex items-center gap-1.5">
                        <CountryFlag code={p.country} />
                        {p.country ?? "—"}
                        {p.timezone ? ` · ${p.timezone}` : ""}
                      </span>
                    </td>
                    <td className="tabular-nums text-slate-400">{p.accounts_count ?? 0}</td>
                    <td className="text-slate-300 tabular-nums">
                      {p.last_known_ip ?? "—"}
                    </td>
                    <td
                      className={
                        p.last_geo_country &&
                        p.country &&
                        p.last_geo_country.toUpperCase() !== p.country.toUpperCase()
                          ? "text-amber-300"
                          : "text-slate-400"
                      }
                      title={
                        p.last_geo_country &&
                        p.country &&
                        p.last_geo_country.toUpperCase() !== p.country.toUpperCase()
                          ? `Mismatch with advertised country (${p.country})`
                          : undefined
                      }
                    >
                      <span
                        className={
                          p.last_geo_country &&
                          p.country &&
                          p.last_geo_country.toUpperCase() !== p.country.toUpperCase()
                            ? "inline-flex items-center gap-1.5 text-amber-300"
                            : "inline-flex items-center gap-1.5"
                        }
                      >
                        <CountryFlag code={p.last_geo_country} />
                        {p.last_geo_country ?? "—"}
                      </span>
                    </td>
                    <td>
                      <StatusBadge value={p.is_healthy ? "ok" : "bad"} />
                    </td>
                    <td className="text-right whitespace-nowrap">
                      <div className="flex items-center justify-end gap-1 flex-wrap">
                        <button
                          type="button"
                          className="btn-ghost text-xs"
                          aria-label={`Edit proxy ${p.label}`}
                          onClick={() => setEditingProxy(p)}
                        >
                          <Pencil size={14} />
                          Edit
                        </button>
                        <button
                          type="button"
                          className="btn-ghost text-xs text-rose-300 disabled:opacity-40"
                          aria-label={`Delete proxy ${p.label}`}
                          disabled={(p.accounts_count ?? 0) > 0}
                          title={
                            (p.accounts_count ?? 0) > 0
                              ? `${p.accounts_count} account(s) use this proxy — reassign them first`
                              : "Remove this proxy"
                          }
                          onClick={async () => {
                            if ((p.accounts_count ?? 0) > 0) return;
                            if (
                              !window.confirm(`Delete proxy "${p.label}" permanently?`)
                            )
                              return;
                            try {
                              await api.proxies.remove(p.label);
                              await reload();
                              push(`Proxy ${p.label} removed`, "info");
                            } catch (err) {
                              push((err as Error).message, "error");
                            }
                          }}
                        >
                          <Trash2 size={14} />
                          Delete
                        </button>
                        <button
                          type="button"
                          className="btn-ghost text-xs"
                          aria-label={`Health check proxy ${p.label}`}
                          onClick={async () => {
                            try {
                              const updated = await api.proxies.check(p.label);
                              setProxies((arr) =>
                                arr.map((x) => (x.id === updated.id ? updated : x))
                              );
                              push(
                                `Proxy ${p.label}: ${updated.is_healthy ? "healthy" : "unhealthy"}`,
                                updated.is_healthy ? "success" : "error"
                              );
                            } catch (err) {
                              push((err as Error).message, "error");
                            }
                          }}
                        >
                          <RefreshCw size={14} />
                          Check
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card
        title="Accounts"
        description={`${accounts.length} configured`}
        actions={
          accounts.length > 0 ? (
            <button
              type="button"
              className="btn-ghost text-xs"
              disabled={testingAll}
              onClick={testAllConnections}
            >
              <RefreshCw size={14} className={testingAll ? "animate-spin" : ""} />
              {testingAll
                ? `Checking ${testAllProgress.done}/${testAllProgress.total}…`
                : "Test all"}
            </button>
          ) : undefined
        }
      >
        {accounts.length === 0 ? (
          <div className="text-sm text-slate-500">No accounts yet.</div>
        ) : (
          <div className="overflow-x-auto -mx-5">
            <table className="table-base">
              <thead>
                <tr>
                  <th>Username</th>
                  <th>Status</th>
                  <th>Proxy</th>
                  <th>TZ</th>
                  <th>Profile</th>
                  <th>Cap / Gap</th>
                  <th>Today</th>
                  <th>Last publish</th>
                  <th>Cooldown till</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {accounts.map((a) => (
                  <tr key={a.id} className="hover:bg-slate-900/40">
                    <td className="font-medium">
                      <div>
                        @{a.username}
                        {a.has_totp ? (
                          <span
                            className="ml-2 text-[10px] uppercase tracking-wide text-emerald-400"
                            title="TOTP seed configured"
                          >
                            2FA
                          </span>
                        ) : null}
                        {a.has_session_id ? (
                          <span
                            className="ml-2 text-[10px] uppercase tracking-wide text-brand-300"
                            title="Browser session cookie imported"
                          >
                            Session
                          </span>
                        ) : null}
                        {a.session_file_exists ? (
                          <span
                            className="ml-2 text-[10px] uppercase tracking-wide text-sky-300"
                            title={
                              a.session_file_updated_at
                                ? `Cookies on disk · ${new Date(a.session_file_updated_at).toLocaleString()}`
                                : "Cookies stored on disk"
                            }
                          >
                            Cookies
                          </span>
                        ) : null}
                      </div>
                      <a
                        href={`https://www.instagram.com/${encodeURIComponent(a.username)}/`}
                        target="_blank"
                        rel="noreferrer"
                        className="mt-1 inline-flex items-center gap-1 text-xs font-normal text-brand-300 hover:text-brand-200"
                      >
                        <ExternalLink size={12} />
                        Open Instagram
                      </a>
                    </td>
                    <td>
                      <StatusBadge value={a.status} />
                    </td>
                    <td className="text-slate-400">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <CountryFlag code={a.proxy_country} />
                        <span>{a.proxy_label ?? "—"}</span>
                        {a.proxy_is_healthy != null ? (
                          <StatusBadge value={a.proxy_is_healthy ? "ok" : "bad"} />
                        ) : null}
                        {a.proxy_label ? (
                          <button
                            type="button"
                            className="btn-ghost text-[10px] px-1 py-0"
                            aria-label={`Connection check for ${a.username}`}
                            title={
                              a.proxy_last_ip
                                ? `Last proxy IP: ${a.proxy_last_ip}`
                                : "Full connection check"
                            }
                            onClick={() => setConnectionAccount(a)}
                          >
                            <Network size={12} /> Connection
                          </button>
                        ) : null}
                      </div>
                    </td>
                    <td className="text-slate-400">{a.timezone}</td>
                    <td className="text-slate-400 capitalize">
                      {a.caption_profile ?? "—"}
                    </td>
                    <td className="text-slate-300 tabular-nums">
                      {a.daily_post_cap} · {a.min_gap_hours}h
                    </td>
                    <td className="tabular-nums">
                      <span className="text-emerald-300">{a.posts_today}</span>
                      <span className="text-slate-500"> / </span>
                      <span className={a.failures_today ? "text-rose-300" : "text-slate-500"}>
                        {a.failures_today}
                      </span>
                    </td>
                    <td className="text-slate-400 text-xs">
                      {a.last_publish_at
                        ? new Date(a.last_publish_at).toLocaleString()
                        : "—"}
                    </td>
                    <td className="text-orange-300 text-xs tabular-nums">
                      {a.cooldown_until
                        ? new Date(a.cooldown_until).toLocaleString()
                        : "—"}
                    </td>
                    <td className="text-right whitespace-nowrap">
                      <div className="flex items-center justify-end gap-1 flex-wrap">
                        <button
                          type="button"
                          className="btn-ghost text-xs"
                          aria-label={`Connection for ${a.username}`}
                          onClick={() => setConnectionAccount(a)}
                        >
                          <Network size={14} /> Connection
                        </button>
                        <button
                          type="button"
                          className="btn-ghost text-xs"
                          aria-label={`Session for ${a.username}`}
                          onClick={() => setSessionAccount(a)}
                        >
                          <KeyRound size={14} /> Session
                        </button>
                        <button
                          type="button"
                          className="btn-ghost text-xs"
                          aria-label={`Change proxy for ${a.username}`}
                          onClick={() => setAssigningAccount(a)}
                        >
                          <Server size={14} /> Change proxy
                        </button>
                        {a.status === "active" ? (
                          <button
                            className="btn-ghost text-xs"
                            onClick={async () => {
                              try {
                                const updated = await api.accounts.pause(a.username);
                                setAccounts((arr) =>
                                  arr.map((x) => (x.id === updated.id ? updated : x))
                                );
                                push(`@${a.username} paused`, "info");
                              } catch (err) {
                                push((err as Error).message, "error");
                              }
                            }}
                          >
                            <Pause size={14} /> Pause
                          </button>
                        ) : (
                          <button
                            className="btn-ghost text-xs"
                            onClick={async () => {
                              try {
                                const updated = await api.accounts.resume(a.username);
                                setAccounts((arr) =>
                                  arr.map((x) => (x.id === updated.id ? updated : x))
                                );
                                push(`@${a.username} resumed`, "success");
                              } catch (err) {
                                push((err as Error).message, "error");
                              }
                            }}
                          >
                            <Play size={14} /> Resume
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <AddAccountModal
        open={openAccount}
        proxies={proxies}
        onClose={() => setOpenAccount(false)}
        onSaved={onCreatedAccount}
      />
      <AddProxyModal
        open={openProxy}
        onClose={() => setOpenProxy(false)}
        onSaved={onCreatedProxy}
      />
      <AssignProxyModal
        account={assigningAccount}
        proxies={proxies}
        open={assigningAccount !== null}
        onClose={() => setAssigningAccount(null)}
        onSaved={onAssignedProxy}
      />
      <ConnectionModal
        account={connectionAccount}
        open={connectionAccount !== null}
        onClose={() => setConnectionAccount(null)}
        onOpenProxy={() => {
          if (connectionAccount) {
            setAssigningAccount(connectionAccount);
            setConnectionAccount(null);
          }
        }}
        onOpenSession={() => {
          if (connectionAccount) {
            setSessionAccount(connectionAccount);
            setConnectionAccount(null);
          }
        }}
        onResult={(account, result) => {
          if (result.proxy_label) {
            const label = result.proxy_label;
            setProxies((arr) =>
              arr.map((x) =>
                x.label === label
                  ? {
                      ...x,
                      is_healthy: result.proxy_health.ok,
                      last_known_ip: result.proxy_health.ip ?? x.last_known_ip,
                      last_geo_country:
                        result.proxy_health.geo_country ?? x.last_geo_country,
                      instagram_reachable: result.proxy_health.instagram_reachable,
                      geo_mismatch_warning: result.proxy_health.geo_mismatch,
                    }
                  : x
              )
            );
          }
          setAccounts((arr) =>
            arr.map((x) =>
              x.id === account.id
                ? {
                    ...x,
                    proxy_is_healthy: result.proxy_health.ok,
                    proxy_geo_country:
                      result.proxy_health.geo_country ?? x.proxy_geo_country,
                    proxy_last_ip: result.proxy_health.ip ?? x.proxy_last_ip,
                    session_file_exists: result.session_storage.session_file_exists,
                    session_source: result.session_storage.session_source,
                  }
                : x
            )
          );
        }}
      />
      <SessionModal
        account={sessionAccount}
        open={sessionAccount !== null}
        onClose={() => setSessionAccount(null)}
        onSaved={onImportedSession}
      />
      <EditProxyModal
        proxy={editingProxy}
        open={editingProxy !== null}
        onClose={() => setEditingProxy(null)}
        onSaved={onUpdatedProxy}
      />
    </div>
  );
}

function AddAccountModal({
  open,
  proxies,
  onClose,
  onSaved,
}: {
  open: boolean;
  proxies: ProxyOut[];
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}) {
  const { push } = useToast();
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState<AccountIn>({
    username: "",
    password: "",
    proxy_label: "",
    timezone: "UTC",
    daily_post_cap: 3,
    min_gap_hours: 4,
    active_hour_start: 10,
    active_hour_end: 22,
    caption_profile: "",
    totp_seed: "",
    email: "",
    email_password: "",
  });

  useEffect(() => {
    if (open && proxies.length > 0 && !form.proxy_label) {
      setForm((f) => ({ ...f, proxy_label: proxies[0].label }));
    }
  }, [open, proxies, form.proxy_label]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.username || !form.password || !form.proxy_label) {
      push("Fill username, password and proxy", "error");
      return;
    }
    setBusy(true);
    try {
      const payload: AccountIn = {
        ...form,
        caption_profile: form.caption_profile?.trim() ? form.caption_profile : null,
        totp_seed: form.totp_seed?.trim() ? form.totp_seed.trim() : null,
        email: form.email?.trim() ? form.email.trim() : null,
        email_password: form.email_password?.trim() ? form.email_password : null,
      };
      await api.accounts.create(payload);
      await onSaved();
      setForm({
        username: "",
        password: "",
        proxy_label: proxies[0]?.label ?? "",
        timezone: "UTC",
        daily_post_cap: 3,
        min_gap_hours: 4,
        active_hour_start: 10,
        active_hour_end: 22,
        caption_profile: "",
        totp_seed: "",
        email: "",
        email_password: "",
      });
    } catch (err) {
      push((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Add account"
      footer={
        <>
          <button onClick={onClose} className="btn-ghost">
            <XCircle size={16} /> Cancel
          </button>
          <button form="add-account-form" type="submit" className="btn-primary" disabled={busy}>
            <CheckCircle2 size={16} />
            {busy ? "Saving..." : "Save account"}
          </button>
        </>
      }
    >
      <form id="add-account-form" onSubmit={submit} className="space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div>
            <label className="label">Username</label>
            <input
              className="input"
              value={form.username}
              onChange={(e) => setForm({ ...form, username: e.target.value })}
              autoComplete="off"
            />
          </div>
          <div>
            <label className="label">Password</label>
            <input
              className="input"
              type="password"
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              autoComplete="new-password"
            />
          </div>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div>
            <label className="label">Proxy</label>
            {proxies.length === 0 ? (
              <div className="flex items-center gap-2 text-sm text-amber-300">
                <ShieldOff size={16} />
                <span>No proxies. Add one first.</span>
              </div>
            ) : (
              <select
                className="input"
                value={form.proxy_label}
                onChange={(e) => setForm({ ...form, proxy_label: e.target.value })}
              >
                {proxies.map((p) => (
                  <option key={p.id} value={p.label}>
                    {p.label} {p.country ? `(${p.country})` : ""}
                  </option>
                ))}
              </select>
            )}
          </div>
          <div>
            <label className="label">Timezone</label>
            <input
              className="input"
              value={form.timezone}
              onChange={(e) => setForm({ ...form, timezone: e.target.value })}
              placeholder="Europe/Berlin"
            />
          </div>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div>
            <label className="label">Daily cap</label>
            <input
              type="number"
              className="input"
              min={1}
              max={20}
              value={form.daily_post_cap ?? 3}
              onChange={(e) => setForm({ ...form, daily_post_cap: Number(e.target.value) })}
            />
          </div>
          <div>
            <label className="label">Min gap (h)</label>
            <input
              type="number"
              step="0.5"
              className="input"
              min={0.5}
              max={24}
              value={form.min_gap_hours ?? 4}
              onChange={(e) => setForm({ ...form, min_gap_hours: Number(e.target.value) })}
            />
          </div>
          <div>
            <label className="label">Active start</label>
            <input
              type="number"
              className="input"
              min={0}
              max={23}
              value={form.active_hour_start ?? 10}
              onChange={(e) => setForm({ ...form, active_hour_start: Number(e.target.value) })}
            />
          </div>
          <div>
            <label className="label">Active end</label>
            <input
              type="number"
              className="input"
              min={1}
              max={23}
              value={form.active_hour_end ?? 22}
              onChange={(e) => setForm({ ...form, active_hour_end: Number(e.target.value) })}
            />
          </div>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div>
            <label className="label">Caption profile</label>
            <select
              className="input"
              value={form.caption_profile ?? ""}
              onChange={(e) => setForm({ ...form, caption_profile: e.target.value })}
            >
              <option value="">— default —</option>
              {CAPTION_PROFILE_OPTIONS.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
            <p className="text-xs text-slate-500 mt-1">
              Tunes caption pool and hashtag tiers per topic.
            </p>
          </div>
          <div>
            <label className="label">TOTP seed (optional)</label>
            <input
              className="input"
              value={form.totp_seed ?? ""}
              onChange={(e) => setForm({ ...form, totp_seed: e.target.value })}
              placeholder="JBSWY3DPEHPK3PXP"
              autoComplete="off"
            />
            <p className="text-xs text-slate-500 mt-1">
              Base32 secret for auto 2FA. Stored locally.
            </p>
          </div>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div>
            <label className="label">Recovery email (optional)</label>
            <input
              className="input"
              type="email"
              value={form.email ?? ""}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
              autoComplete="off"
            />
          </div>
          <div>
            <label className="label">Email password / app password</label>
            <input
              className="input"
              type="password"
              value={form.email_password ?? ""}
              onChange={(e) => setForm({ ...form, email_password: e.target.value })}
              autoComplete="new-password"
            />
            <p className="text-xs text-slate-500 mt-1">
              Used for IMAP-based challenge code retrieval.
            </p>
          </div>
        </div>
      </form>
    </Modal>
  );
}

function ConnectionModal({
  account,
  open,
  onClose,
  onOpenProxy,
  onOpenSession,
  onResult,
}: {
  account: AccountOut | null;
  open: boolean;
  onClose: () => void;
  onOpenProxy: () => void;
  onOpenSession: () => void;
  onResult?: (account: AccountOut, result: AccountConnectionTestOut) => void;
}) {
  const { push } = useToast();
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<AccountConnectionTestOut | null>(null);
  const [history, setHistory] = useState<DiagnosticRunOut[]>([]);
  const [selectedHistoryId, setSelectedHistoryId] = useState<number | "current">("current");

  useEffect(() => {
    if (!open) return;
    setResult(null);
    setRunning(false);
    setSelectedHistoryId("current");
    setHistory([]);
  }, [open, account?.username]);

  const connectionUsername = account?.username;
  useEffect(() => {
    if (!open || !connectionUsername) return;
    let cancelled = false;
    api.diagnostics
      .list({ username: connectionUsername, kind: "connection_test", limit: 5 })
      .then((rows) => {
        if (!cancelled) setHistory(rows);
      })
      .catch(() => {
        if (!cancelled) setHistory([]);
      });
    return () => {
      cancelled = true;
    };
  }, [open, connectionUsername, result?.run_id]);

  async function runTest() {
    if (!account) return;
    setRunning(true);
    setResult(null);
    try {
      const data = await api.accounts.testConnection(account.username);
      setResult(data);
      onResult?.(account, data);
      push(
        data.overall_ok
          ? `@${account.username}: ready for autoposting`
          : `@${account.username}: connection issues found`,
        data.overall_ok ? "success" : "error"
      );
    } catch (err) {
      push((err as Error).message, "error");
    } finally {
      setRunning(false);
    }
  }

  const step1: StepVisual = running
    ? "running"
    : result
      ? result.proxy_assigned
        ? "ok"
        : "fail"
      : account?.proxy_label
        ? "ok"
        : "pending";

  const step2: StepVisual = running
    ? "running"
    : result
      ? result.proxy_health.ok
        ? result.proxy_health.geo_mismatch
          ? "warn"
          : "ok"
        : "fail"
      : "pending";

  const step3: StepVisual = running
    ? "running"
    : result
      ? result.proxy_health.instagram_reachable
        ? "ok"
        : "fail"
      : "pending";

  const step4: StepVisual = running
    ? "running"
    : result
      ? result.instagram_auth.ok
        ? "ok"
        : result.instagram_auth.challenge
          ? "warn"
          : "fail"
      : "pending";

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Connection · @${account?.username ?? ""}`}
      footer={
        <>
          <button type="button" onClick={onClose} className="btn-ghost">
            <XCircle size={16} /> Close
          </button>
          <button
            type="button"
            className="btn-primary"
            disabled={running || !account}
            onClick={runTest}
          >
            <RefreshCw size={16} className={running ? "animate-spin" : ""} />
            {running ? "Checking…" : "Run check"}
          </button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-3 text-sm space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-slate-400">Proxy:</span>
            <CountryFlag code={account?.proxy_country} />
            <span className="font-mono text-xs">{account?.proxy_label ?? "—"}</span>
            {account?.proxy_last_ip ? (
              <span className="text-xs text-slate-500">· {account.proxy_last_ip}</span>
            ) : null}
          </div>
          <div className="flex flex-wrap gap-2 text-[10px] uppercase tracking-wide">
            {account?.has_session_id ? (
              <span className="text-brand-300">DB sessionid</span>
            ) : null}
            {account?.session_file_exists ? (
              <span className="text-sky-300">Cookies file</span>
            ) : null}
            {account ? (
              <span className="text-slate-500">{sessionSourceLabel(account.session_source)}</span>
            ) : null}
          </div>
        </div>

        <div className="space-y-2">
          <ConnectionStepRow
            label="1. Proxy assigned"
            state={step1}
            detail={
              result
                ? result.proxy_label ?? "No proxy"
                : account?.proxy_label ?? "Not assigned"
            }
          />
          <ConnectionStepRow
            label="2. Proxy responds"
            state={step2}
            detail={
              result?.proxy_health.ok ? (
                <span className="inline-flex items-center gap-2 flex-wrap">
                  IP: {result.proxy_health.ip ?? "—"}
                  <CountryFlag code={result.proxy_health.geo_country} showCode />
                  {result.proxy_health.geo_mismatch ? (
                    <span className="text-amber-300">Geo mismatch with advertised country</span>
                  ) : null}
                </span>
              ) : (
                result?.proxy_health.error ?? (running ? "Checking proxy…" : "Not tested yet")
              )
            }
          />
          <ConnectionStepRow
            label="3. Instagram reachable via proxy"
            state={step3}
            detail={
              result
                ? result.proxy_health.instagram_reachable
                  ? "TLS handshake to Instagram succeeded"
                  : "Proxy cannot reach Instagram"
                : running
                  ? "Probing Instagram…"
                  : "Not tested yet"
            }
          />
          <ConnectionStepRow
            label="4. Session valid"
            state={step4}
            detail={
              result?.instagram_auth.ok ? (
                <span>
                  Authenticated via {result.instagram_auth.method}
                  {result.instagram_auth.ig_username
                    ? ` · @${result.instagram_auth.ig_username}`
                    : ""}
                </span>
              ) : (
                result?.instagram_auth.error ??
                (running ? "Validating session…" : "Not tested yet")
              )
            }
          />
        </div>

        {result ? (
          <div
            className={`rounded-xl border p-3 text-sm ${
              result.overall_ok
                ? "border-emerald-800/60 bg-emerald-950/30 text-emerald-200"
                : "border-rose-800/60 bg-rose-950/30 text-rose-200"
            }`}
          >
            <div className="font-medium">
              {result.overall_ok
                ? "Ready for autoposting"
                : "Not ready for autoposting"}
            </div>
            {!result.overall_ok && result.instagram_auth.error ? (
              <div className="mt-1 text-xs opacity-90">{result.instagram_auth.error}</div>
            ) : null}
            {result.checked_at ? (
              <div className="mt-1 text-xs opacity-70">
                Checked {new Date(result.checked_at).toLocaleString()}
              </div>
            ) : null}
          </div>
        ) : null}

        <div className="space-y-2">
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <div className="text-xs font-medium text-slate-400 uppercase tracking-wide">
              Diagnostic log
            </div>
            {history.length > 0 ? (
              <select
                className="input py-1 text-xs max-w-[220px]"
                value={selectedHistoryId === "current" ? "current" : String(selectedHistoryId)}
                onChange={(e) => {
                  const v = e.target.value;
                  setSelectedHistoryId(v === "current" ? "current" : Number(v));
                }}
              >
                <option value="current">Latest check</option>
                {history.map((h) => (
                  <option key={h.id} value={h.id}>
                    {new Date(h.created_at).toLocaleString()} — {h.status}
                  </option>
                ))}
              </select>
            ) : null}
          </div>
          <DiagnosticLogPanel
            lines={
              selectedHistoryId === "current"
                ? result?.logs ?? []
                : history.find((h) => h.id === selectedHistoryId)?.logs ?? []
            }
            emptyLabel={running ? "Running check…" : "Run check to see step-by-step logs."}
            maxHeightClass="max-h-64"
          />
        </div>

        <div className="flex flex-wrap gap-2">
          <button type="button" className="btn-ghost text-xs" onClick={onOpenProxy}>
            <Server size={14} /> Change proxy
          </button>
          <button type="button" className="btn-ghost text-xs" onClick={onOpenSession}>
            <KeyRound size={14} /> Import session
          </button>
        </div>
      </div>
    </Modal>
  );
}

function SessionModal({
  account,
  open,
  onClose,
  onSaved,
}: {
  account: AccountOut | null;
  open: boolean;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}) {
  const { push } = useToast();
  const [tab, setTab] = useState<"import" | "export">("import");
  const [busy, setBusy] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [verifyResult, setVerifyResult] = useState<AccountConnectionTestOut | null>(null);
  const [sessionId, setSessionId] = useState("");
  const [exportData, setExportData] = useState<AccountSessionOut | null>(null);
  const [exportLoading, setExportLoading] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setTab("import");
    setSessionId("");
    setExportData(null);
    setExportError(null);
    setVerifyResult(null);
  }, [open, account?.username]);

  useEffect(() => {
    if (!open || !account || tab !== "export") return;
    let cancelled = false;
    setExportLoading(true);
    setExportError(null);
    setExportData(null);
    api.accounts
      .getSession(account.username)
      .then((data) => {
        if (!cancelled) setExportData(data);
      })
      .catch((err) => {
        if (!cancelled) setExportError((err as Error).message);
      })
      .finally(() => {
        if (!cancelled) setExportLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, account, tab]);

  async function submitImport(e: React.FormEvent) {
    e.preventDefault();
    if (!account) return;
    const trimmed = sessionId.trim();
    if (trimmed.length < 31) {
      push("Paste a valid sessionid cookie (31+ characters)", "error");
      return;
    }
    setBusy(true);
    try {
      const payload: AccountSessionUpdate = { session_id: trimmed };
      await api.accounts.updateSession(account.username, payload);
      await onSaved();
    } catch (err) {
      push((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  async function copyExport() {
    if (!exportData?.session_id) return;
    try {
      await navigator.clipboard.writeText(exportData.session_id);
      push("Session copied", "success");
    } catch {
      push("Copy failed", "error");
    }
  }

  async function verifySession() {
    if (!account) return;
    setVerifying(true);
    setVerifyResult(null);
    try {
      const data = await api.accounts.testConnection(account.username);
      setVerifyResult(data);
      push(
        data.instagram_auth.ok ? "Session is valid" : "Session validation failed",
        data.instagram_auth.ok ? "success" : "error"
      );
    } catch (err) {
      push((err as Error).message, "error");
    } finally {
      setVerifying(false);
    }
  }

  const title = `Session · @${account?.username ?? ""}`;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      footer={
        tab === "import" ? (
          <>
            <button type="button" onClick={onClose} className="btn-ghost">
              <XCircle size={16} /> Cancel
            </button>
            <button
              form="import-session-form"
              type="submit"
              className="btn-primary"
              disabled={busy}
            >
              <CheckCircle2 size={16} />
              {busy ? "Saving..." : "Save session"}
            </button>
          </>
        ) : (
          <button type="button" onClick={onClose} className="btn-ghost">
            <XCircle size={16} /> Close
          </button>
        )
      }
    >
      <div className="flex gap-1 mb-4 p-1 rounded-lg bg-slate-900/60 border border-slate-800">
        <button
          type="button"
          className={`flex-1 text-sm py-1.5 rounded-md ${
            tab === "import" ? "bg-slate-800 text-white" : "text-slate-400 hover:text-slate-200"
          }`}
          onClick={() => setTab("import")}
        >
          Import
        </button>
        <button
          type="button"
          className={`flex-1 text-sm py-1.5 rounded-md ${
            tab === "export" ? "bg-slate-800 text-white" : "text-slate-400 hover:text-slate-200"
          }`}
          onClick={() => setTab("export")}
        >
          Export
        </button>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-3 text-sm mb-4 space-y-2">
        <div className="text-slate-400">Session storage (per account)</div>
        <div className="flex flex-wrap gap-2 text-xs">
          <span className={account?.has_session_id ? "text-brand-300" : "text-slate-500"}>
            DB sessionid: {account?.has_session_id ? "yes" : "no"}
          </span>
          <span className={account?.session_file_exists ? "text-sky-300" : "text-slate-500"}>
            Cookies file: {account?.session_file_exists ? "yes" : "no"}
          </span>
          <span className="text-slate-400">
            Source: {account ? sessionSourceLabel(account.session_source) : "—"}
          </span>
        </div>
        {account?.session_file_updated_at ? (
          <div className="text-xs text-slate-500">
            Cookies updated {new Date(account.session_file_updated_at).toLocaleString()}
          </div>
        ) : null}
        <button
          type="button"
          className="btn-ghost text-xs mt-1"
          disabled={verifying || !account}
          onClick={verifySession}
        >
          <RefreshCw size={14} className={verifying ? "animate-spin" : ""} />
          {verifying ? "Verifying…" : "Verify session"}
        </button>
        {verifyResult ? (
          <div
            className={`text-xs rounded-lg p-2 ${
              verifyResult.instagram_auth.ok
                ? "text-emerald-300 bg-emerald-950/40"
                : "text-rose-300 bg-rose-950/40"
            }`}
          >
            {verifyResult.instagram_auth.ok
              ? `Valid via ${verifyResult.instagram_auth.method}${
                  verifyResult.instagram_auth.ig_username
                    ? ` (@${verifyResult.instagram_auth.ig_username})`
                    : ""
                }`
              : verifyResult.instagram_auth.error ?? "Session invalid"}
          </div>
        ) : null}
      </div>

      {tab === "import" ? (
        <form id="import-session-form" onSubmit={submitImport} className="space-y-4">
          <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-3 text-sm">
            <div className="text-slate-400">Instagram account</div>
            <div className="font-medium">@{account?.username ?? "—"}</div>
            <div className="mt-2 text-slate-400">Current status</div>
            <div className="text-xs">
              {account?.has_session_id ? (
                <span className="text-brand-300">Session cookie on file — paste to replace</span>
              ) : (
                <span className="text-slate-500">No session imported yet</span>
              )}
            </div>
          </div>
          <div>
            <label className="label" htmlFor="import-session-id">
              sessionid cookie
            </label>
            <textarea
              id="import-session-id"
              className="input min-h-[88px] font-mono text-xs"
              value={sessionId}
              onChange={(e) => setSessionId(e.target.value)}
              placeholder="Paste sessionid from Dolphin / browser devtools"
              autoComplete="off"
              spellCheck={false}
            />
            <p className="text-xs text-slate-500 mt-1">
              Import after confirming the challenge in Dolphin on the same proxy.
            </p>
          </div>
        </form>
      ) : (
        <div className="space-y-4">
          <p className="text-xs text-amber-300/90">
            Sensitive data — copy only into trusted tools (Dolphin, backup).
          </p>
          {exportLoading ? (
            <div className="text-sm text-slate-400">Loading session…</div>
          ) : exportError ? (
            <div className="text-sm text-slate-400 rounded-xl border border-slate-800 p-3">
              {exportError.includes("404") || exportError.toLowerCase().includes("not found")
                ? "No session found — import a sessionid or log in first."
                : exportError}
            </div>
          ) : exportData ? (
            <>
              <div className="text-xs text-slate-500">
                Source:{" "}
                <span className="text-slate-300">
                  {exportData.source === "database" ? "database" : "saved session file"}
                </span>
                {exportData.session_file_exists ? " · session file on disk" : null}
              </div>
              <textarea
                readOnly
                className="input min-h-[88px] font-mono text-xs"
                value={exportData.session_id}
              />
              <button type="button" className="btn-primary text-sm" onClick={copyExport}>
                <Copy size={14} /> Copy sessionid
              </button>
            </>
          ) : null}
        </div>
      )}
    </Modal>
  );
}

function AssignProxyModal({
  account,
  proxies,
  open,
  onClose,
  onSaved,
}: {
  account: AccountOut | null;
  proxies: ProxyOut[];
  open: boolean;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}) {
  const { push } = useToast();
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(false);
  const [proxyLabel, setProxyLabel] = useState("");
  const [testResult, setTestResult] = useState<ProxyOut | null>(null);

  useEffect(() => {
    if (!open || !account) return;
    const currentExists = proxies.some((p) => p.label === account.proxy_label);
    setProxyLabel(currentExists ? account.proxy_label ?? "" : proxies[0]?.label ?? "");
    setTestResult(null);
  }, [account, open, proxies]);

  const selectedProxy = proxies.find((p) => p.label === proxyLabel) ?? null;

  async function runProxyTest() {
    if (!proxyLabel) {
      push("Select a proxy", "error");
      return;
    }
    setTesting(true);
    try {
      const updated = await api.proxies.check(proxyLabel);
      setTestResult(updated);
    } catch (err) {
      push((err as Error).message, "error");
    } finally {
      setTesting(false);
    }
  }

  async function testAndSave() {
    if (!account || !proxyLabel) return;
    setTesting(true);
    setBusy(true);
    try {
      const updated = await api.proxies.check(proxyLabel);
      setTestResult(updated);
      if (!updated.is_healthy) {
        push("Proxy unhealthy — not saved", "error");
        return;
      }
      if (updated.instagram_reachable === false) {
        push("Instagram unreachable through proxy — not saved", "error");
        return;
      }
      const payload: AccountProxyUpdate = { proxy_label: proxyLabel };
      await api.accounts.updateProxy(account.username, payload);
      await onSaved();
      push("Proxy tested and saved", "success");
    } catch (err) {
      push((err as Error).message, "error");
    } finally {
      setTesting(false);
      setBusy(false);
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!account) return;
    if (proxies.length === 0) {
      push("Add a proxy first", "error");
      return;
    }
    if (!proxyLabel) {
      push("Select a proxy", "error");
      return;
    }
    setBusy(true);
    try {
      const payload: AccountProxyUpdate = { proxy_label: proxyLabel };
      await api.accounts.updateProxy(account.username, payload);
      await onSaved();
    } catch (err) {
      push((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Change proxy · @${account?.username ?? ""}`}
      footer={
        <>
          <button type="button" onClick={onClose} className="btn-ghost">
            <XCircle size={16} /> Cancel
          </button>
          <button
            type="button"
            className="btn-ghost"
            disabled={busy || testing || proxies.length === 0 || !proxyLabel}
            onClick={testAndSave}
          >
            <RefreshCw size={16} className={testing ? "animate-spin" : ""} />
            Test &amp; save
          </button>
          <button
            form="assign-proxy-form"
            type="submit"
            className="btn-primary"
            disabled={busy || proxies.length === 0}
          >
            <CheckCircle2 size={16} />
            {busy ? "Saving..." : "Save proxy"}
          </button>
        </>
      }
    >
      <form id="assign-proxy-form" onSubmit={submit} className="space-y-4">
        <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-3 text-sm">
          <div className="text-slate-400">Instagram account</div>
          <div className="font-medium">@{account?.username ?? "—"}</div>
          <div className="mt-2 text-slate-400">Current proxy</div>
          <div className="font-mono text-xs">{account?.proxy_label ?? "—"}</div>
        </div>
        <div>
          <label className="label">Proxy</label>
          {proxies.length === 0 ? (
            <div className="flex items-center gap-2 text-sm text-amber-300">
              <ShieldOff size={16} />
              <span>No proxies. Add one first.</span>
            </div>
          ) : (
            <div className="space-y-2">
              <div className="flex gap-2">
                <select
                  className="input flex-1"
                  value={proxyLabel}
                  onChange={(e) => {
                    setProxyLabel(e.target.value);
                    setTestResult(null);
                  }}
                >
                  {proxies.map((p) => (
                    <option key={p.id} value={p.label}>
                      {proxyOptionLabel(p)}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className="btn-ghost shrink-0"
                  disabled={testing || !proxyLabel}
                  aria-label="Test selected proxy in modal"
                  onClick={runProxyTest}
                >
                  <RefreshCw size={14} className={testing ? "animate-spin" : ""} />
                  {testing ? "Testing…" : "Test proxy"}
                </button>
              </div>
              {selectedProxy ? (
                <div className="flex items-center gap-2 text-xs text-slate-400">
                  <CountryFlag code={selectedProxy.country} showCode />
                </div>
              ) : null}
              {testResult ? (
                <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-3 text-xs space-y-1">
                  <div className="flex items-center gap-2">
                    <StatusBadge value={testResult.is_healthy ? "ok" : "bad"} />
                    <span className="text-slate-300">
                      {testResult.is_healthy ? "Healthy" : "Unhealthy"}
                    </span>
                  </div>
                  <div className="text-slate-400">
                    IP: <span className="text-slate-200">{testResult.last_known_ip ?? "—"}</span>
                  </div>
                  <div className="text-slate-400 flex items-center gap-1.5">
                    Geo:
                    <CountryFlag code={testResult.last_geo_country} showCode />
                    {testResult.geo_mismatch_warning ? (
                      <span className="text-amber-300">Mismatch</span>
                    ) : null}
                  </div>
                  <div className="text-slate-400">
                    Instagram:{" "}
                    <span
                      className={
                        testResult.instagram_reachable === false
                          ? "text-rose-300"
                          : testResult.instagram_reachable
                            ? "text-emerald-300"
                            : "text-slate-500"
                      }
                    >
                      {testResult.instagram_reachable === false
                        ? "unreachable"
                        : testResult.instagram_reachable
                          ? "reachable"
                          : "—"}
                    </span>
                  </div>
                  {testResult.last_checked_at ? (
                    <div className="text-slate-500">
                      Checked {new Date(testResult.last_checked_at).toLocaleString()}
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          )}
          <p className="text-xs text-slate-500 mt-1">
            All Instagram actions for this account will use the selected proxy.
          </p>
        </div>
      </form>
    </Modal>
  );
}

function EditProxyModal({
  proxy,
  open,
  onClose,
  onSaved,
}: {
  proxy: ProxyOut | null;
  open: boolean;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}) {
  const { push } = useToast();
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState<ProxyUpdate>({
    url: "",
    country: "",
    timezone: "",
    notes: "",
    skip_health_check: false,
  });

  useEffect(() => {
    if (!proxy || !open) return;
    setForm({
      url: proxy.url,
      country: proxy.country ?? "",
      timezone: proxy.timezone ?? "",
      notes: proxy.notes ?? "",
      skip_health_check: false,
    });
  }, [proxy, open]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!proxy || !form.url.trim()) {
      push("URL required", "error");
      return;
    }
    setBusy(true);
    try {
      const payload: ProxyUpdate = {
        url: form.url.trim(),
        country: form.country?.trim() ? form.country.trim() : null,
        timezone: form.timezone?.trim() ? form.timezone.trim() : null,
        notes: form.notes?.trim() ? form.notes : null,
        skip_health_check: form.skip_health_check,
      };
      await api.proxies.update(proxy.label, payload);
      await onSaved();
    } catch (err) {
      push((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  const label = proxy?.label ?? "";

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Edit proxy · ${label}`}
      footer={
        <>
          <button type="button" onClick={onClose} className="btn-ghost">
            <XCircle size={16} /> Cancel
          </button>
          <button form="edit-proxy-form" type="submit" className="btn-primary" disabled={busy}>
            <CheckCircle2 size={16} />
            {busy ? "Saving..." : "Save changes"}
          </button>
        </>
      }
    >
      <form id="edit-proxy-form" onSubmit={submit} className="space-y-3">
        <div>
          <label className="label">URL</label>
          <input
            className="input font-mono text-sm"
            placeholder="http://user:pass@host:port"
            value={form.url}
            onChange={(e) => setForm({ ...form, url: e.target.value })}
          />
          <p className="text-xs text-slate-500 mt-1">
            Stored in the database for this workspace.
          </p>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label">Country</label>
            <input
              className="input"
              maxLength={8}
              value={form.country ?? ""}
              onChange={(e) => setForm({ ...form, country: e.target.value })}
            />
          </div>
          <div>
            <label className="label">Timezone</label>
            <input
              className="input"
              value={form.timezone ?? ""}
              onChange={(e) => setForm({ ...form, timezone: e.target.value })}
            />
          </div>
        </div>
        <div>
          <label className="label">Notes</label>
          <textarea
            className="input min-h-[60px]"
            value={form.notes ?? ""}
            onChange={(e) => setForm({ ...form, notes: e.target.value })}
          />
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-300">
          <input
            type="checkbox"
            className="h-4 w-4 rounded border-slate-600 bg-slate-900"
            checked={form.skip_health_check}
            onChange={(e) =>
              setForm({ ...form, skip_health_check: e.target.checked })
            }
          />
          <span>Skip health check after save</span>
        </label>
      </form>
    </Modal>
  );
}

function AddProxyModal({
  open,
  onClose,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}) {
  const { push } = useToast();
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState<ProxyIn>({
    label: "",
    url: "",
    country: "",
    timezone: "",
    notes: "",
    skip_health_check: false,
  });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.label || !form.url) {
      push("Fill label and URL", "error");
      return;
    }
    setBusy(true);
    try {
      await api.proxies.create(form);
      await onSaved();
      setForm({ label: "", url: "", country: "", timezone: "", notes: "", skip_health_check: false });
    } catch (err) {
      push((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Add proxy"
      footer={
        <>
          <button onClick={onClose} className="btn-ghost">
            <XCircle size={16} /> Cancel
          </button>
          <button form="add-proxy-form" type="submit" className="btn-primary" disabled={busy}>
            <CheckCircle2 size={16} />
            {busy ? "Saving..." : "Save proxy"}
          </button>
        </>
      }
    >
      <form id="add-proxy-form" onSubmit={submit} className="space-y-3">
        <div>
          <label className="label">Label</label>
          <input
            className="input"
            value={form.label}
            onChange={(e) => setForm({ ...form, label: e.target.value })}
          />
        </div>
        <div>
          <label className="label">URL</label>
          <input
            className="input"
            placeholder="http://user:pass@host:port"
            value={form.url}
            onChange={(e) => setForm({ ...form, url: e.target.value })}
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label">Country</label>
            <input
              className="input"
              maxLength={8}
              value={form.country ?? ""}
              onChange={(e) => setForm({ ...form, country: e.target.value })}
            />
          </div>
          <div>
            <label className="label">Timezone</label>
            <input
              className="input"
              value={form.timezone ?? ""}
              onChange={(e) => setForm({ ...form, timezone: e.target.value })}
            />
          </div>
        </div>
        <div>
          <label className="label">Notes</label>
          <textarea
            className="input min-h-[60px]"
            value={form.notes ?? ""}
            onChange={(e) => setForm({ ...form, notes: e.target.value })}
          />
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-300">
          <input
            type="checkbox"
            className="h-4 w-4 rounded border-slate-600 bg-slate-900"
            checked={form.skip_health_check}
            onChange={(e) =>
              setForm({ ...form, skip_health_check: e.target.checked })
            }
          />
          <span>Skip health check on save</span>
        </label>
      </form>
    </Modal>
  );
}
