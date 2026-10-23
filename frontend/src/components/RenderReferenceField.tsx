import clsx from "clsx";
import { ImagePlus, X } from "lucide-react";
import { useRef, useState } from "react";

import { formatApiError } from "../api/client";
import { mediaApiPath } from "../api/media";
import { useToast } from "../context/ToastContext";
import {
  MAX_IMAGE_REFERENCES,
  clipboardMediaFiles,
  filesFromDataTransfer,
  mediaKind,
  mergeReferences,
  modeAfterReferences,
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
  value: RenderReference[];
  libraryFiles: LibraryFile[];
  inputMode: RenderInputMode;
  onChange: (next: RenderReference[]) => void;
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
  const imageCount = value.filter((item) => item.mediaType === "image").length;
  const room = imageCount < MAX_IMAGE_REFERENCES;

  const publish = (incoming: RenderReference[]) => {
    const before = value.filter((item) => item.mediaType === "image").length;
    const next = mergeReferences(value, incoming);
    const after = next.filter((item) => item.mediaType === "image").length;
    if (incoming.some((item) => item.mediaType === "image") && after === before && before >= MAX_IMAGE_REFERENCES) {
      push(`Не больше ${MAX_IMAGE_REFERENCES} фото`, "error");
    }
    onChange(next);
    onInputModeChange(modeAfterReferences(inputMode, next));
  };

  const applyFiles = async (files: File[]) => {
    const media = files.filter((file) => mediaKind(file));
    if (!media.length) {
      push("Нужны jpg, png, webp или короткое mp4", "error");
      return;
    }
    setUploading(true);
    try {
      const uploaded: RenderReference[] = [];
      for (const file of media) {
        uploaded.push(await uploadRenderReference(file));
      }
      publish(uploaded);
    } catch (err) {
      push(formatApiError(err), "error");
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const pickLibrary = (filename: string) => {
    if (!filename) return;
    const item = libraryFiles.find((file) => file.filename === filename);
    const mediaType = item?.media_type === "video" ? "video" : "image";
    publish([
      {
        filename,
        mediaType,
        previewUrl: mediaApiPath(filename),
      },
    ]);
  };

  const remove = (filename: string) => {
    const next = value.filter((item) => item.filename !== filename);
    onChange(next);
    onInputModeChange(modeAfterReferences(inputMode, next));
  };

  return (
    <div className="space-y-2">
      <div className="text-sm text-slate-200">Пример для генерации</div>
      <div className="space-y-3 rounded-xl border border-slate-800 p-3">
        {value.length ? (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {value.map((item) => (
              <div key={item.filename} className="flex min-w-0 flex-col gap-1">
                {item.mediaType === "video" ? (
                  <video
                    src={item.previewUrl || mediaApiPath(item.filename)}
                    className="h-[72px] w-full rounded-md border border-slate-700 bg-black object-cover"
                    muted
                    playsInline
                    preload="metadata"
                  />
                ) : (
                  <img
                    src={item.previewUrl || mediaApiPath(item.filename)}
                    alt=""
                    className="h-[72px] w-full rounded-md border border-slate-700 object-cover"
                  />
                )}
                <div className="truncate text-xs text-slate-300" title={item.filename}>
                  {item.filename}
                </div>
                <button
                  type="button"
                  className="btn-ghost btn-compact min-h-[44px] w-full justify-center"
                  disabled={busy}
                  aria-label={`Убрать ${item.filename}`}
                  onClick={() => remove(item.filename)}
                >
                  <X className="h-3.5 w-3.5" />
                  Убрать
                </button>
              </div>
            ))}
          </div>
        ) : null}

        {room ? (
          <div
            tabIndex={0}
            aria-label="Зона референсов"
            onDragOver={(event) => {
              event.preventDefault();
              if (!busy) setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragging(false);
              if (busy) return;
              void filesFromDataTransfer(event.dataTransfer).then((files) => {
                if (files.length) void applyFiles(files);
              });
            }}
            onPaste={(event) => {
              const files = clipboardMediaFiles(event.nativeEvent);
              if (!files.length) return;
              event.preventDefault();
              void applyFiles(files);
            }}
            className={clsx(
              "flex flex-col items-center gap-2 rounded-xl border border-dashed border-slate-700 bg-slate-900/40 px-4 py-5 text-center outline-none focus:border-brand-500",
              dragging && "border-brand-500 bg-brand-500/10",
              busy && "opacity-60"
            )}
          >
            <ImagePlus className="h-5 w-5 text-slate-400" />
            <p className="text-sm text-slate-300">
              {uploading ? "Загрузка…" : "Перетащите фото, папку или короткое видео"}
            </p>
            <button
              type="button"
              className="btn-ghost btn-compact"
              disabled={busy}
              onClick={() => inputRef.current?.click()}
            >
              Выбрать файлы
            </button>
            <input
              ref={inputRef}
              type="file"
              multiple
              accept={ACCEPT}
              className="hidden"
              aria-label="Выбрать файл референса"
              disabled={busy}
              onChange={(event) => {
                const files = Array.from(event.target.files ?? []);
                if (files.length) void applyFiles(files);
              }}
            />
          </div>
        ) : null}

        <label className="block text-sm text-slate-400">
          добавить из библиотеки
          <select
            className="input mt-1"
            aria-label="или из библиотеки"
            disabled={busy}
            value=""
            onChange={(event) => pickLibrary(event.target.value)}
          >
            <option value="">не выбрано</option>
            {libraryFiles
              .filter((file) => file.media_type === "image" || file.media_type === "video")
              .map((file) => (
                <option key={file.filename} value={file.filename}>
                  {file.media_type === "image" ? "фото" : "видео"} · {file.filename}
                </option>
              ))}
          </select>
        </label>

        {value.length ? (
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
          Несколько фото — референс для ролика. Первое фото задаёт «По фото». Ken Burns проходит
          каждый кадр. Короткое mp4 заменяет список и переносит движение.
        </p>
        {backendNote ? <p className="text-xs text-amber-300/90">{backendNote}</p> : null}
      </div>
    </div>
  );
}
