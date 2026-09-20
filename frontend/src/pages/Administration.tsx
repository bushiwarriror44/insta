import { BookOpen } from "lucide-react";
import { useEffect, useRef } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { AdministrationNotebook } from "../components/AdministrationNotebook";
import { PageHeader } from "../components/PageHeader";
import { SaladGpuCard } from "../components/SaladGpuCard";
import { useAuth } from "../context/AuthContext";
import { ARCHITECTURE_SECTIONS } from "./architecture";
import { COST_SECTIONS } from "./costs";

import "swagger-ui-dist/swagger-ui.css";
import "./administration.css";

type AdminTab = "overview" | "notes" | "api";

const TABS: { id: AdminTab; label: string }[] = [
  { id: "overview", label: "Обзор" },
  { id: "notes", label: "Блокнот" },
  { id: "api", label: "API" },
];

function tabFromHash(hash: string): AdminTab {
  const key = hash.replace(/^#/, "");
  if (key === "notes" || key === "api" || key === "overview") return key;
  return "overview";
}

function hashForTab(tab: AdminTab): string {
  return tab === "overview" ? "" : `#${tab}`;
}

export function Administration() {
  const { role, state } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const host = useRef<HTMLDivElement>(null);
  const token = state.state === "authed" ? state.token : "";
  const tab = tabFromHash(location.hash);

  const selectTab = (id: AdminTab) => {
    const hash = hashForTab(id);
    if (tabFromHash(location.hash) === id) return;
    navigate({ pathname: location.pathname, search: location.search, hash }, { replace: true });
  };

  useEffect(() => {
    const onHash = () => {
      const next = tabFromHash(window.location.hash);
      if (next === tabFromHash(location.hash)) return;
      navigate(
        { pathname: location.pathname, search: location.search, hash: hashForTab(next) },
        { replace: true },
      );
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [location.hash, location.pathname, location.search, navigate]);

  useEffect(() => {
    if (role === "operator" || tab !== "api") return;
    const node = host.current;
    if (!node) return;
    let cancelled = false;
    let ui: { destroy?: () => void } | undefined;

    void import("swagger-ui-dist/swagger-ui-bundle.js").then((mod) => {
      if (cancelled || !host.current) return;
      ui = mod.default({
        domNode: host.current,
        url: "/api/openapi.json",
        tryItOutEnabled: true,
        filter: true,
        deepLinking: true,
        docExpansion: "list",
        defaultModelsExpandDepth: -1,
        displayRequestDuration: true,
        persistAuthorization: true,
        requestInterceptor: (req) => {
          if (token) {
            req.headers = { ...req.headers, Authorization: `Bearer ${token}` };
          }
          return req;
        },
      });
    });

    return () => {
      cancelled = true;
      ui?.destroy?.();
      node.replaceChildren();
    };
  }, [role, token, tab]);

  if (role === "operator") {
    return <Navigate to="/" replace />;
  }

  return (
    <div className="flex min-h-[calc(100vh-11rem)] flex-col gap-4">
      <PageHeader
        icon={BookOpen}
        title="Администрирование"
        description="Обзор (GPU и оплата), блокнот владельца и живая схема API. Try it out вызывает те же эндпоинты, что и панель; токен сессии подставляется сам."
      />
      <div className="admin-tabs" role="tablist" aria-label="Разделы администрирования">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            id={`admin-tab-${item.id}`}
            aria-selected={tab === item.id}
            aria-controls={`admin-panel-${item.id}`}
            className="admin-tab"
            onClick={() => selectTab(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>
      {tab === "overview" ? (
        <div id="admin-panel-overview" role="tabpanel" aria-labelledby="admin-tab-overview" className="space-y-4">
          <SaladGpuCard />
          <section className="card space-y-2 p-4" aria-labelledby="costs-heading">
            <h2 id="costs-heading" className="text-lg font-semibold text-slate-100">
              Оплата
            </h2>
            {COST_SECTIONS.map((section) => (
              <details key={section.id} open className="rounded-lg border border-slate-800 bg-slate-950/50 px-3 py-2">
                <summary className="cursor-pointer text-sm font-medium text-slate-200">{section.title}</summary>
                <div className="mt-2 space-y-2 text-sm leading-relaxed text-slate-400">
                  {section.body.map((paragraph) => (
                    <p key={paragraph}>{paragraph}</p>
                  ))}
                </div>
              </details>
            ))}
          </section>
          <section className="card space-y-2 p-4" aria-labelledby="architecture-heading">
            <h2 id="architecture-heading" className="text-lg font-semibold text-slate-100">
              Реализация
            </h2>
            {ARCHITECTURE_SECTIONS.map((section) => (
              <details key={section.id} open className="rounded-lg border border-slate-800 bg-slate-950/50 px-3 py-2">
                <summary className="cursor-pointer text-sm font-medium text-slate-200">{section.title}</summary>
                <div className="mt-2 space-y-2 text-sm leading-relaxed text-slate-400">
                  {section.body.map((paragraph) => (
                    <p key={paragraph}>{paragraph}</p>
                  ))}
                </div>
              </details>
            ))}
          </section>
        </div>
      ) : null}
      {tab === "notes" ? (
        <div id="admin-panel-notes" role="tabpanel" aria-labelledby="admin-tab-notes">
          <AdministrationNotebook />
        </div>
      ) : null}
      {tab === "api" ? (
        <div
          id="admin-panel-api"
          role="tabpanel"
          aria-labelledby="admin-tab-api"
          ref={host}
          data-testid="swagger-host"
          className="swagger-panel min-h-[36rem] flex-1 overflow-auto rounded-2xl border border-slate-800 bg-slate-900/40 p-3"
        />
      ) : null}
    </div>
  );
}
