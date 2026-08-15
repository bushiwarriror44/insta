import { useEffect, useState } from "react";
import { BrowserRouter } from "react-router-dom";

import App from "../App";
import { api } from "../api/client";
import { AuthProvider } from "../context/AuthContext";
import { ToastProvider } from "../context/ToastContext";
import { Fake500 } from "./Fake500";

type GateState =
  | { status: "loading" }
  | { status: "denied" }
  | { status: "error"; message: string }
  | { status: "allowed"; basename: string };

export function GateRoot() {
  const [gate, setGate] = useState<GateState>({ status: "loading" });
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setGate({ status: "loading" });
    (async () => {
      const path = window.location.pathname || "/";
      try {
        const res = await api.panel.gate(path);
        if (cancelled) return;
        if (!res.allowed) {
          setGate({ status: "denied" });
          return;
        }
        const basename = res.entry_path && res.entry_path !== "/" ? res.entry_path : "/";
        setGate({ status: "allowed", basename });
      } catch (err) {
        if (cancelled) return;
        const message = err instanceof Error ? err.message : "API недоступен";
        setGate({ status: "error", message });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [tick]);

  if (gate.status === "loading") {
    return (
      <div
        data-testid="gate-loading"
        style={{
          minHeight: "100vh",
          margin: 0,
          background: "#f0f0f0",
        }}
      />
    );
  }

  if (gate.status === "denied") {
    return <Fake500 />;
  }

  if (gate.status === "error") {
    return (
      <div
        data-testid="gate-error"
        style={{
          fontFamily: "Tahoma, Geneva, Verdana, sans-serif",
          background: "#f0f0f0",
          color: "#222",
          minHeight: "100vh",
          margin: 0,
          padding: "48px 24px",
        }}
      >
        <h1 style={{ fontSize: "20px", fontWeight: "normal", margin: "0 0 12px" }}>
          Сервис временно недоступен
        </h1>
        <p style={{ margin: "0 0 16px", fontSize: "14px", color: "#555" }}>{gate.message}</p>
        <button
          type="button"
          data-testid="gate-retry"
          onClick={() => setTick((n) => n + 1)}
          style={{
            fontSize: "14px",
            padding: "8px 14px",
            cursor: "pointer",
            border: "1px solid #ccc",
            background: "#fff",
          }}
        >
          Повторить
        </button>
      </div>
    );
  }

  return (
    <BrowserRouter basename={gate.basename === "/" ? undefined : gate.basename}>
      <ToastProvider>
        <AuthProvider>
          <App />
        </AuthProvider>
      </ToastProvider>
    </BrowserRouter>
  );
}
