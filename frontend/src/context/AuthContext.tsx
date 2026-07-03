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

import { api, ApiError, configureAuth } from "../api/client";

const STORAGE_KEY = "reels-admin-token";

type AuthState =
  | { state: "loading" }
  | { state: "open" }
  | { state: "needs-login" }
  | { state: "authed"; token: string };

interface AuthCtx {
  state: AuthState;
  login: (token: string) => Promise<boolean>;
  logout: () => void;
  authRequired: boolean;
}

const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const tokenRef = useRef<string | null>(null);
  const [state, setState] = useState<AuthState>({ state: "loading" });
  const [authRequired, setAuthRequired] = useState<boolean>(false);

  useEffect(() => {
    configureAuth(() => tokenRef.current);
  }, []);

  useEffect(() => {
    let cancelled = false;
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
              tokenRef.current = null;
            }
          }
        }
        if (!cancelled) setState({ state: "needs-login" });
      } catch {
        if (!cancelled) setState({ state: "needs-login" });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (token: string) => {
    tokenRef.current = token;
    try {
      await api.dashboard();
      window.localStorage.setItem(STORAGE_KEY, token);
      setState({ state: "authed", token });
      return true;
    } catch {
      tokenRef.current = null;
      return false;
    }
  }, []);

  const logout = useCallback(() => {
    tokenRef.current = null;
    window.localStorage.removeItem(STORAGE_KEY);
    setState({ state: "needs-login" });
  }, []);

  const value = useMemo<AuthCtx>(
    () => ({ state, login, logout, authRequired }),
    [state, login, logout, authRequired]
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
