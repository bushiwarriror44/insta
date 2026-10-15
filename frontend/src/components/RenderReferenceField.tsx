import clsx from "clsx";
import { ImagePlus, X } from "lucide-react";
import { useRef, useState } from "react";

import { formatApiError } from "../api/client";
import { mediaApiPath } from "../api/media";
import { useToast } from "../context/ToastContext";
import {
  modeForMedia,
  uploadRenderReference,
  type RenderInputMode,
  type RenderReference,
} from "../lib/referenceUpload";

const ACCEPT = "image/*,video/mp4,video/quicktime,.jpg,.jpeg,.png,.webp,.mp4,.mov";

const MODES: { id: RenderInputMode; label: string }[] = [
  { id: "image_to_video", label: "По фото" },
  { id: "video_to_video", label: "По видео" },
  { id: "image_slideshow", label: "Ken Burns" },
];

type LibraryFile = { filename: string; media_type: string };

interface Props {
  value: RenderReference | null;
  libraryFiles: LibraryFile[];
  inputMode: RenderInputMode;
  onChange: (next: RenderReference | null) => void;
  onInputModeChange: (mode: RenderInputMode) => void;
  disabled?: boolean;
  backendNote?: string | null;
}

export function RenderReferenceField({
  value,
  libraryFiles,
  inputMode,
  onChange,
  onInputModeChange,
  disabled,
  backendNote,
}: Props) {
  const { push } = useToast();
  const inputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const busy = disabled || uploading;

  const applyFile = async (file: File) => {
    setUploading(true);
    try {
      const next = await uploadRenderReference(file);
      onChange(next);
      onInputModeChange(modeForMedia(next.mediaType));
    } catch (err) {
      push(formatApiError(err), "error");
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const pickLibrary = (filename: string) => {
    if (!filename) {
      onChange(null);
      onInputModeChange("");
      return;
    }
    const item = libraryFiles.find((file) => file.filename === filename);
    const mediaType = item?.media_type === "video" ? "video" : "image";
    onChange({
      filename,
      mediaType,
      previewUrl: mediaApiPath(filename),
    });
    onInputModeChange(modeForMedia(mediaType));
  };

  return (
    <div className="space-y-2">
      <div className="text-sm text-slate-200">Пример для генерации</div>
      <div className="space-y-3 rounded-xl border border-slate-800 p-3">
        {value ? (
          <div className="flex items-center gap-3">
            {value.mediaType === "video" ? (
              <video
                src={value.previewUrl || mediaApiPath(value.filename)}
                className="h-[72px] w-[72px] rounded-md border border-slate-700 bg-black object-cover"
                muted
                playsInline
                preload="metadata"
              />
            ) : (
              <img
                src={value.previewUrl || mediaApiPath(value.filename)}
                alt=""
                className="h-[72px] w-[72px] rounded-md border border-slate-700 object-cover"
              />
            )}
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm text-slate-200" title={value.filename}>
                {value.filename}
              </div>
              <div className="text-xs text-slate-500">
                {value.mediaType === "video" ? "Видео-референс" : "Фото-референс"}
              </div>
            </div>
            <button
              type="button"
              className="btn-ghost btn-compact shrink-0"
              disabled={busy}
              onClick={() => {
                onChange(null);
                onInputModeChange("");
              }}
            >
              <X className="h-4 w-4" />
              Убрать
            </button>
          </div>
        ) : (
          <div
            onDragOver={(event) => {
              event.preventDefault();
              if (!busy) setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragging(false);
              if (busy) return;
              const file = event.dataTransfer.files?.[0];
              if (file) void applyFile(file);
            }}
            className={clsx(
              "flex flex-col items-center gap-2 rounded-xl border border-dashed border-slate-700 bg-slate-900/40 px-4 py-5 text-center",
              dragging && "border-brand-500 bg-brand-500/10",
              busy && "opacity-60"
            )}
          >
            <ImagePlus className="h-5 w-5 text-slate-400" />
            <p className="text-sm text-slate-300">
              {uploading ? "Загрузка…" : "Перетащите фото или короткое видео"}
            </p>
            <button
              type="button"
              className="btn-ghost btn-compact"
              disabled={busy}
              onClick={() => inputRef.current?.click()}
            >
              Выбрать файл
            </button>
            <input
              ref={inputRef}
              type="file"
              accept={ACCEPT}
              className="hidden"
              aria-label="Выбрать файл референса"
              disabled={busy}
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void applyFile(file);
              }}
            />
          </div>
        )}

        <label className="block text-sm text-slate-400">
          или из библиотеки
          <select
            className="input mt-1"
            aria-label="или из библиотеки"
            disabled={busy}
            value={value?.filename ?? ""}
            onChange={(event) => pickLibrary(event.target.value)}
          >
            <option value="">без референса</option>
            {libraryFiles
              .filter((file) => file.media_type === "image" || file.media_type === "video")
              .map((file) => (
                <option key={file.filename} value={file.filename}>
                  {file.media_type === "image" ? "фото" : "видео"} · {file.filename}
                </option>
              ))}
          </select>
        </label>

        {value ? (
          <div className="flex flex-wrap gap-2" role="group" aria-label="режим референса">
            {MODES.map((mode) => (
              <button
                key={mode.id}
                type="button"
                aria-pressed={inputMode === mode.id}
                className={clsx(
                  "rounded-full px-2.5 py-1 text-xs ring-1 transition-colors",
                  inputMode === mode.id
                    ? "bg-brand-600/20 text-brand-200 ring-brand-500/40"
                    : "text-slate-400 ring-slate-700 hover:bg-slate-800/60"
                )}
                onClick={() => onInputModeChange(mode.id)}
              >
                {mode.label}
              </button>
            ))}
          </div>
        ) : null}

        <p className="text-xs leading-relaxed text-slate-500">
          Фото — похожее видео (I2V). Короткое mp4 — перенос движения (V2V). Ken Burns — слайдшоу
          без нейросети.
        </p>
        {backendNote ? <p className="text-xs text-amber-300/90">{backendNote}</p> : null}
      </div>
    </div>
  );
}
