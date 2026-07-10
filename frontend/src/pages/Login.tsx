import { LogIn, ShieldCheck } from "lucide-react";
import { useState } from "react";

import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";

export function Login() {
  const { login } = useAuth();
  const { push } = useToast();
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!token.trim()) return;
    setBusy(true);
    const ok = await login(token.trim());
    setBusy(false);
    if (!ok) push("Неверный токен", "error");
  }

  return (
    <div className="min-h-screen grid place-items-center bg-gradient-to-b from-slate-950 via-slate-950 to-slate-900 px-4">
      <div className="card w-full max-w-md p-8">
        <div className="flex items-center justify-center mb-5">
          <div className="rounded-2xl bg-brand-500/15 p-3 text-brand-300">
            <ShieldCheck size={28} />
          </div>
        </div>
        <h1 className="text-2xl font-semibold text-center">Reels Admin</h1>
        <p className="text-sm text-slate-400 text-center mt-1">
          Введите токен администратора для входа.
        </p>
        <form className="mt-6 space-y-4" onSubmit={submit}>
          <div>
            <label className="label" htmlFor="token">
              Токен администратора
            </label>
            <input
              id="token"
              type="password"
              className="input"
              placeholder="вставьте ADMIN_TOKEN"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              autoFocus
            />
          </div>
          <button type="submit" className="btn-primary w-full" disabled={busy}>
            <LogIn size={16} />
            <span>{busy ? "Проверка..." : "Войти"}</span>
          </button>
        </form>
      </div>
    </div>
  );
}
