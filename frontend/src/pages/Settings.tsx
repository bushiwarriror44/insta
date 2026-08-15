import { Copy, KeyRound, Save, Settings as SettingsIcon } from "lucide-react";
import type { FormEvent } from "react";
import { useCallback, useEffect, useState } from "react";
import { Navigate } from "react-router-dom";

import { api, formatApiError } from "../api/client";
import type { PanelSettingsOut } from "../api/types";
import { copyTextToClipboard } from "../components/DiagnosticLogPanel";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";

export function Settings() {
  const { role } = useAuth();
  const { push } = useToast();
  const [data, setData] = useState<PanelSettingsOut | null>(null);
  const [loading, setLoading] = useState(true);

  const [pathDraft, setPathDraft] = useState("");
  const [pathPassword, setPathPassword] = useState("");
  const [pathBusy, setPathBusy] = useState(false);

  const [curPw, setCurPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [newPw2, setNewPw2] = useState("");
  const [pwBusy, setPwBusy] = useState(false);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const out = await api.settings.get();
      setData(out);
      setPathDraft(out.entry_path);
    } catch (err) {
      push(formatApiError(err), "error");
    } finally {
      setLoading(false);
    }
  }, [push]);

  useEffect(() => {
    if (role === "owner") void reload();
  }, [role, reload]);

  if (role !== "owner") {
    return <Navigate to="/" replace />;
  }

  async function copyPath() {
    if (!data?.entry_path) return;
    const full = `${window.location.origin}${data.entry_path}`;
    const ok = await copyTextToClipboard(full);
    push(ok ? "URL скопирован" : "Не удалось скопировать", ok ? "success" : "error");
  }

  async function onSavePath(e: FormEvent) {
    e.preventDefault();
    if (!pathPassword.trim()) {
      push("Введите текущий мастер-пароль", "error");
      return;
    }
    setPathBusy(true);
    try {
      const out = await api.settings.updateEntryPath(pathDraft.trim(), pathPassword.trim());
      setData(out);
      setPathPassword("");
      push("Путь обновлён — перезагрузка…", "success");
      window.location.replace(`${out.entry_path}/`);
    } catch (err) {
      push(formatApiError(err), "error");
    } finally {
      setPathBusy(false);
    }
  }

  async function onSavePassword(e: FormEvent) {
    e.preventDefault();
    if (newPw !== newPw2) {
      push("Новый пароль и подтверждение не совпадают", "error");
      return;
    }
    if (newPw.trim().length < 8) {
      push("Новый пароль: минимум 8 символов", "error");
      return;
    }
    setPwBusy(true);
    try {
      const out = await api.settings.updateMasterPassword(curPw.trim(), newPw.trim());
      setData(out);
      setCurPw("");
      setNewPw("");
      setNewPw2("");
      push("Мастер-пароль обновлён. Войдите снова при необходимости.", "success");
    } catch (err) {
      push(formatApiError(err), "error");
    } finally {
      setPwBusy(false);
    }
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <SettingsIcon size={22} />
          Настройки
        </h1>
        <p className="text-sm text-slate-400 mt-1">
          Секретный URL админки и мастер-пароль. Только для владельца.
        </p>
      </div>

      {loading || !data ? (
        <p className="text-slate-500 text-sm">Загрузка…</p>
      ) : (
        <>
          <section className="card p-4 space-y-3">
            <h2 className="text-sm font-medium text-slate-200">Секретный путь</h2>
            <p className="text-xs text-slate-500">
              Корень сайта показывает ошибку 500. Панель открывается только по этому URL.
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <code className="flex-1 min-w-0 rounded-lg border border-slate-700 bg-slate-950/60 px-3 py-2 text-xs break-all">
                {window.location.origin}
                {data.entry_path}
              </code>
              <button type="button" className="btn-ghost text-xs" onClick={() => void copyPath()}>
                <Copy size={14} />
                Копировать
              </button>
            </div>

            <form onSubmit={onSavePath} className="space-y-3 pt-2 border-t border-slate-800">
              <div>
                <label className="label" htmlFor="settings-path">
                  Новый путь
                </label>
                <input
                  id="settings-path"
                  className="input font-mono text-xs"
                  value={pathDraft}
                  onChange={(e) => setPathDraft(e.target.value)}
                  placeholder="/mySecretPath12"
                  autoComplete="off"
                />
              </div>
              <div>
                <label className="label" htmlFor="settings-path-pw">
                  Текущий мастер-пароль
                </label>
                <input
                  id="settings-path-pw"
                  type="password"
                  className="input"
                  value={pathPassword}
                  onChange={(e) => setPathPassword(e.target.value)}
                  autoComplete="current-password"
                />
              </div>
              <button type="submit" className="btn-primary" disabled={pathBusy}>
                <Save size={16} />
                {pathBusy ? "Сохранение…" : "Сохранить путь"}
              </button>
            </form>
          </section>

          <section className="card p-4 space-y-3">
            <h2 className="text-sm font-medium text-slate-200 flex items-center gap-2">
              <KeyRound size={16} />
              Мастер-пароль
            </h2>
            <p className="text-xs text-slate-500">
              {data.master_password_set
                ? "Задан пароль в БД (ADMIN_TOKEN из .env по-прежнему принимается как запасной)."
                : "Сейчас вход владельца — через ADMIN_TOKEN. Можно задать отдельный мастер-пароль."}
            </p>
            <form onSubmit={onSavePassword} className="space-y-3">
              <div>
                <label className="label" htmlFor="settings-cur-pw">
                  Текущий пароль / ADMIN_TOKEN
                </label>
                <input
                  id="settings-cur-pw"
                  type="password"
                  className="input"
                  value={curPw}
                  onChange={(e) => setCurPw(e.target.value)}
                  autoComplete="current-password"
                />
              </div>
              <div>
                <label className="label" htmlFor="settings-new-pw">
                  Новый пароль
                </label>
                <input
                  id="settings-new-pw"
                  type="password"
                  className="input"
                  value={newPw}
                  onChange={(e) => setNewPw(e.target.value)}
                  autoComplete="new-password"
                />
              </div>
              <div>
                <label className="label" htmlFor="settings-new-pw2">
                  Подтверждение
                </label>
                <input
                  id="settings-new-pw2"
                  type="password"
                  className="input"
                  value={newPw2}
                  onChange={(e) => setNewPw2(e.target.value)}
                  autoComplete="new-password"
                />
              </div>
              <button type="submit" className="btn-primary" disabled={pwBusy}>
                <Save size={16} />
                {pwBusy ? "Сохранение…" : "Сменить мастер-пароль"}
              </button>
            </form>
          </section>
        </>
      )}
    </div>
  );
}
