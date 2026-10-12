import { useCallback, useEffect, useRef, useState } from "react";
import { Save } from "lucide-react";

import { api, formatApiError } from "../api/client";
import { useToast } from "../context/ToastContext";

const DEBOUNCE_MS = 2000;

type SaveStatus = "idle" | "saving" | "saved" | "error";

function statusLabel(status: SaveStatus, dirty: boolean): string {
  if (status === "saving") return "Сохраняем…";
  if (status === "error") return "Не сохранилось";
  if (dirty) return "Есть несохранённые правки";
  if (status === "saved") return "Сохранено";
  return "Сохранено в SQLite";
}

export function AdministrationNotebook() {
  const { push } = useToast();
  const [draft, setDraft] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [status, setStatus] = useState<SaveStatus>("idle");
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const savedRef = useRef("");

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const out = await api.adminNotes.get();
        if (cancelled) return;
        setDraft(out.content);
        savedRef.current = out.content;
        setUpdatedAt(out.updated_at);
        setLoaded(true);
      } catch (err) {
        if (!cancelled) push(formatApiError(err), "error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [push]);

  const save = useCallback(
    async (value: string) => {
      if (value === savedRef.current) {
        setDirty(false);
        setStatus("saved");
        return;
      }
      setStatus("saving");
      try {
        const out = await api.adminNotes.update(value);
        savedRef.current = out.content;
        setUpdatedAt(out.updated_at);
        setDirty(false);
        setStatus("saved");
      } catch (err) {
        setStatus("error");
        push(formatApiError(err), "error");
      }
    },
    [push]
  );

  useEffect(() => {
    if (!loaded || !dirty) return;
    const id = window.setTimeout(() => {
      void save(draft);
    }, DEBOUNCE_MS);
    return () => window.clearTimeout(id);
  }, [draft, dirty, loaded, save]);

  return (
    <section className="card flex min-h-[24rem] flex-col gap-3 p-4" aria-labelledby="notes-heading">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="notes-heading" className="text-lg font-semibold text-slate-100">
            Блокнот
          </h2>
          <p className="mt-1 max-w-2xl text-sm leading-relaxed text-slate-400">
            Для важного: Salad org/project, напоминания. Не дублируйте секреты — они уже в{" "}
            <code className="text-slate-300">.env</code>. Чат эту заметку не читает.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-slate-500" data-testid="notes-status">
            {statusLabel(status, dirty)}
            {updatedAt ? ` · ${new Date(updatedAt).toLocaleString("ru-RU")}` : ""}
          </span>
          <button
            type="button"
            className="btn-ghost"
            disabled={!loaded || status === "saving"}
            onClick={() => void save(draft)}
          >
            <Save size={14} />
            Сохранить сейчас
          </button>
        </div>
      </div>
      <textarea
        className="input min-h-[20rem] flex-1 resize-y font-mono text-sm leading-relaxed"
        value={draft}
        disabled={!loaded}
        spellCheck={false}
        placeholder="Организация / проект / группа Salad, хост, что не забыть…"
        aria-label="Текст блокнота"
        onChange={(event) => {
          setDraft(event.target.value);
          setDirty(true);
        }}
      />
    </section>
  );
}
