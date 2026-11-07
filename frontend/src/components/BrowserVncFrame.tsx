import { Loader2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { BrowserSessionOut } from "../api/types";

type Props = {
  session: BrowserSessionOut | null;
  adminToken: string | null;
  iframeTitle?: string;
  placeholder?: string;
  minHeightClass?: string;
};

export function BrowserVncFrame({
  session,
  adminToken,
  iframeTitle = "VNC браузер",
  placeholder = "Запустите браузер, чтобы увидеть окно Chrome в noVNC",
  minHeightClass = "h-[600px]",
}: Props) {
  const [vncRevealReady, setVncRevealReady] = useState(false);

  const vncPath = session?.vnc_path?.replace(/^\//, "") ?? "";

  const vncUrl = useMemo(() => {
    if (!vncPath || !session || ["stopped", "error"].includes(session.status)) return null;
    const params = new URLSearchParams({
      autoconnect: "true",
      resize: "scale",
      path: vncPath,
      quality: "3",
      compression: "8",
    });
    if (adminToken) {
      params.set("token", adminToken);
      params.set(
        "path",
        `${vncPath}${vncPath.includes("?") ? "&" : "?"}token=${encodeURIComponent(adminToken)}`
      );
    }
    return `/novnc/vnc.html?${params.toString()}`;
  }, [vncPath, session, adminToken]);

  const live = Boolean(
    session && ["running", "awaiting_code", "starting"].includes(session.status) && vncUrl
  );

  useEffect(() => {
    if (!live) {
      setVncRevealReady(false);
      return;
    }
    const id = window.setTimeout(() => setVncRevealReady(true), 1500);
    return () => clearTimeout(id);
  }, [live, vncUrl]);

  const showVncSkeleton = live && !vncRevealReady;

  return (
    <div className="relative rounded-lg border border-slate-700 bg-black/40 overflow-hidden min-h-[360px]">
      {vncUrl ? (
        <>
          <iframe
            title={iframeTitle}
            src={vncUrl}
            className={`relative z-0 w-full bg-black ${minHeightClass}`}
            allow="clipboard-read; clipboard-write"
          />
          {showVncSkeleton ? (
            <div
              className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 bg-black/55 backdrop-blur-[1px]"
              aria-busy="true"
              aria-label="Подключение к VNC"
            >
              <Loader2 className="h-8 w-8 animate-spin text-slate-400" aria-hidden />
              <span className="text-xs text-slate-400">Подключение к VNC…</span>
            </div>
          ) : null}
        </>
      ) : session?.status === "starting" ? (
        <div className="flex h-[360px] flex-col items-center justify-center gap-3" aria-busy="true">
          <Loader2 className="h-8 w-8 animate-spin text-slate-500" />
          <p className="text-sm text-slate-500">{placeholder}</p>
        </div>
      ) : (
        <div className="flex h-[360px] items-center justify-center text-sm text-slate-500 px-4 text-center">
          {placeholder}
        </div>
      )}
    </div>
  );
}
