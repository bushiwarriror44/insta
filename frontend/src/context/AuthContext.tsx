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
  login: (token: string) => Promise<LoginResult>;
  logout: () => void;
  retryBootstrap: () => void;
  authRequired: boolean;
}

const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const tokenRef = useRef<string | null>(null);
  const [state, setState] = useState<AuthState>({ state: "loading" });
  const [authRequired, setAuthRequired] = useState<boolean>(false);
  const [bootstrapKey, setBootstrapKey] = useState(0);

  useEffect(() => {
    configureAuth(() => tokenRef.current);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setState({ state: "loading" });

    (async () => {
      try {
        const h = await api.health();
        if (cancelled) return;
        setAuthRequired(h.auth_required);
        if (!h.auth_required) {
          tokenRef.current = null;
          setState({ state: "open" });
          return;
        }
        const stored = window.localStorage.getItem(STORAGE_KEY);
        if (stored) {
          tokenRef.current = stored;
          try {
            await api.dashboard();
            if (cancelled) return;
            setState({ state: "authed", token: stored });
            return;
          } catch (err) {
            if (err instanceof ApiError && err.status === 401) {
              window.localStorage.removeItem(STORAGE_KEY);
            }
            tokenRef.current = null;
          }
        } else {
          tokenRef.current = null;
        }
        if (!cancelled) setState({ state: "needs-login" });
      } catch (err) {
        if (cancelled) return;
        tokenRef.current = null;
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
      window.localStorage.setItem(STORAGE_KEY, token);
      setState({ state: "authed", token });
      return { ok: true };
    } catch (err) {
      tokenRef.current = null;
      if (err instanceof ApiError && err.status === 401) {
        return { ok: false, reason: "invalid", message: "Неверный токен" };
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
    setState({ state: "needs-login" });
  }, []);

  const retryBootstrap = useCallback(() => {
    setBootstrapKey((k) => k + 1);
  }, []);

  const value = useMemo<AuthCtx>(
    () => ({ state, login, logout, retryBootstrap, authRequired }),
    [state, login, logout, retryBootstrap, authRequired]
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
