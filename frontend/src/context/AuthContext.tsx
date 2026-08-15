import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";

import { api, ApiError, configureAuth, formatApiError } from "../api/client";
import type { AuthRole } from "../api/types";

const STORAGE_KEY = "reels-admin-token";

export type AuthState =
  | { state: "loading" }
  | { state: "open" }
  | { state: "needs-login" }
  | { state: "authed"; token: string }
  | { state: "error"; message: string };

export type LoginResult =
  | { ok: true }
  | { ok: false; reason: "invalid" | "network"; message: string };

interface AuthCtx {
  state: AuthState;
  role: AuthRole | null;
  login: (token: string) => Promise<LoginResult>;
  logout: () => void;
  retryBootstrap: () => void;
  authRequired: boolean;
}

const Ctx = createContext<AuthCtx | null>(null);

async function fetchRole(): Promise<AuthRole | null> {
  try {
    const me = await api.auth.me();
    return me.role ?? null;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const tokenRef = useRef<string | null>(null);
  const [state, setState] = useState<AuthState>({ state: "loading" });
  const [role, setRole] = useState<AuthRole | null>(null);
  const [authRequired, setAuthRequired] = useState<boolean>(false);
  const [bootstrapKey, setBootstrapKey] = useState(0);

  useEffect(() => {
    configureAuth(() => tokenRef.current);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setState({ state: "loading" });
    setRole(null);

    (async () => {
      try {
        const h = await api.health();
        if (cancelled) return;
        setAuthRequired(h.auth_required);
        if (!h.auth_required) {
          tokenRef.current = null;
          setRole(null);
          setState({ state: "open" });
          return;
        }
        const stored = window.localStorage.getItem(STORAGE_KEY);
        if (stored) {
          tokenRef.current = stored;
          try {
            await api.dashboard();
            const nextRole = await fetchRole();
            if (cancelled) return;
            setRole(nextRole);
            setState({ state: "authed", token: stored });
            return;
          } catch (err) {
            if (err instanceof ApiError && err.status === 401) {
              window.localStorage.removeItem(STORAGE_KEY);
            }
            tokenRef.current = null;
            setRole(null);
          }
        } else {
          tokenRef.current = null;
        }
        if (!cancelled) setState({ state: "needs-login" });
      } catch (err) {
        if (cancelled) return;
        tokenRef.current = null;
        setRole(null);
        setState({
          state: "error",
          message: formatApiError(err),
        });
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [bootstrapKey]);

  const login = useCallback(async (token: string): Promise<LoginResult> => {
    tokenRef.current = token;
    try {
      await api.dashboard();
      const nextRole = await fetchRole();
      window.localStorage.setItem(STORAGE_KEY, token);
      setRole(nextRole);
      setState({ state: "authed", token });
      return { ok: true };
    } catch (err) {
      tokenRef.current = null;
      setRole(null);
      if (err instanceof ApiError && err.status === 401) {
        return { ok: false, reason: "invalid", message: "Неверный пароль" };
      }
      return {
        ok: false,
        reason: "network",
        message: formatApiError(err),
      };
    }
  }, []);

  const logout = useCallback(() => {
    tokenRef.current = null;
    window.localStorage.removeItem(STORAGE_KEY);
    setRole(null);
    setState({ state: "needs-login" });
  }, []);

  const retryBootstrap = useCallback(() => {
    setBootstrapKey((k) => k + 1);
  }, []);

  const value = useMemo<AuthCtx>(
    () => ({ state, role, login, logout, retryBootstrap, authRequired }),
    [state, role, login, logout, retryBootstrap, authRequired]
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
