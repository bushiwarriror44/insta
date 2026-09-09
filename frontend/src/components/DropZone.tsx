import clsx from "clsx";
import { CheckCircle2, UploadCloud, XCircle } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

function fileMatchesAccept(file: File, accept: string): boolean {
  const tokens = accept
    .split(",")
    .map((token) => token.trim().toLowerCase())
    .filter(Boolean);
  if (tokens.length === 0) return true;
  const type = file.type.toLowerCase();
  const name = file.name.toLowerCase();
  return tokens.some((token) => {
    if (token.startsWith(".")) return name.endsWith(token);
    if (token.endsWith("/*")) return type.startsWith(token.slice(0, -1));
    return type === token;
  });
}

interface Props {
  accept?: string;
  disabled?: boolean;
  title?: string;
  hint?: string;
  staging?: boolean;
  multiple?: boolean;
  onFile: (file: File) => void;
  onFiles?: (files: File[]) => void;
}

export function DropZone({
  accept = "video/mp4,video/quicktime",
  disabled,
  title = "Перетащите готовые Reels (.mp4) сюда",
  hint = ".mp4 / .mov",
  staging = false,
  multiple = false,
  onFile,
  onFiles,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!staging || pendingFiles.length === 0) {
      setPreviewUrl(null);
      return;
    }
    if (typeof URL.createObjectURL !== "function") {
      setPreviewUrl(null);
      return;
    }
    const url = URL.createObjectURL(pendingFiles[0]);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [pendingFiles, staging]);

  const clearPending = useCallback(() => {
    setPendingFiles([]);
    if (inputRef.current) inputRef.current.value = "";
  }, []);

  const commitFiles = useCallback(
    (files: File[]) => {
      if (files.length === 0) return;
      if (multiple && onFiles) {
        onFiles(files);
      } else {
        onFile(files[0]);
      }
      clearPending();
    },
    [clearPending, multiple, onFile, onFiles]
  );

  const handleFiles = useCallback(
    (files: FileList | null) => {
      if (!files || files.length === 0) return;
      const list = Array.from(files).filter((file) => fileMatchesAccept(file, accept));
      if (list.length === 0) return;
      if (staging) {
        setPendingFiles(list);
        return;
      }
      commitFiles(list);
    },
    [accept, commitFiles, staging]
  );

  const isVideo = pendingFiles[0]?.type.startsWith("video/");

  if (staging && pendingFiles.length > 0) {
    return (
      <div className="rounded-2xl border border-slate-700 bg-slate-900/50 p-4 space-y-3">
        <div className="flex justify-center">
          {previewUrl && isVideo ? (
            <video
              src={previewUrl}
              className="max-h-48 rounded-lg bg-black aspect-[9/16] max-w-[10rem] w-full object-contain"
              controls
              muted
              playsInline
              preload="metadata"
            />
          ) : previewUrl ? (
            <img
              src={previewUrl}
              alt="Предпросмотр"
              className="max-h-48 rounded-lg object-contain"
            />
          ) : null}
        </div>
        <div className="text-sm text-slate-300 text-center break-all">
          {pendingFiles.length === 1
            ? pendingFiles[0].name
            : `Выбрано файлов: ${pendingFiles.length}`}
        </div>
        <div className="flex gap-2 justify-center">
          <button
            type="button"
            className="btn-ghost"
            disabled={disabled}
            onClick={clearPending}
          >
            <XCircle size={16} /> Отмена
          </button>
          <button
            type="button"
            className="btn-primary"
            disabled={disabled}
            onClick={() => commitFiles(pendingFiles)}
          >
            <CheckCircle2 size={16} />
            {disabled ? "Загрузка…" : "Загрузить"}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div
      onClick={() => !disabled && inputRef.current?.click()}
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setIsDragging(true);
      }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setIsDragging(false);
        if (disabled) return;
        handleFiles(e.dataTransfer.files);
      }}
      className={clsx(
        "rounded-2xl border-2 border-dashed border-slate-700 bg-slate-900/40",
        "flex flex-col items-center justify-center gap-2 px-6 py-12 text-center cursor-pointer",
        "transition-colors hover:border-brand-500/60 hover:bg-slate-900/70",
        isDragging && "border-brand-500 bg-brand-500/10",
        disabled && "opacity-60 cursor-not-allowed"
      )}
    >
      <UploadCloud size={32} className="text-slate-400" />
      <div className="text-sm text-slate-300">
        {title}, или <span className="text-brand-400">нажмите для выбора</span>
      </div>
      <div className="text-xs text-slate-500">{hint}</div>
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        multiple={multiple}
        className="hidden"
        onChange={(e) => handleFiles(e.target.files)}
      />
    </div>
  );
}
