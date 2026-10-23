import { api } from "../api/client";
import { mediaApiPath } from "../api/media";

export const MAX_IMAGE_REFERENCES = 8;

const IMAGE_EXT = new Set([".jpg", ".jpeg", ".png", ".webp"]);
const VIDEO_EXT = new Set([".mp4", ".mov", ".m4v"]);

export type RenderReference = {
  filename: string;
  mediaType: "image" | "video";
  previewUrl?: string;
};

export type RenderInputMode = "" | "image_to_video" | "video_to_video" | "image_slideshow";

export function modeForMedia(mediaType: "image" | "video"): RenderInputMode {
  return mediaType === "video" ? "video_to_video" : "image_to_video";
}

export function mediaKind(file: File): "image" | "video" | null {
  const type = file.type.toLowerCase();
  if (type.startsWith("image/")) return "image";
  if (type.startsWith("video/")) return "video";
  const dot = file.name.lastIndexOf(".");
  const ext = dot >= 0 ? file.name.slice(dot).toLowerCase() : "";
  if (IMAGE_EXT.has(ext)) return "image";
  if (VIDEO_EXT.has(ext)) return "video";
  return null;
}

export function mergeReferences(
  current: RenderReference[],
  incoming: RenderReference[]
): RenderReference[] {
  const incomingVideos = incoming.filter((item) => item.mediaType === "video");
  const incomingImages = incoming.filter((item) => item.mediaType === "image");
  if (incomingVideos.length > 0 && incomingImages.length === 0) {
    return [incomingVideos[0]];
  }
  const next = current.filter((item) => item.mediaType === "image");
  for (const image of incomingImages) {
    if (next.some((item) => item.filename === image.filename)) continue;
    if (next.length >= MAX_IMAGE_REFERENCES) break;
    next.push(image);
  }
  return next;
}

export function modeAfterReferences(
  current: RenderInputMode,
  refs: RenderReference[]
): RenderInputMode {
  if (!refs.length) return "";
  if (refs.some((item) => item.mediaType === "video")) return "video_to_video";
  if (current === "image_slideshow") return current;
  return "image_to_video";
}

type FsEntry = {
  isFile: boolean;
  isDirectory: boolean;
  file: (ok: (file: File) => void, err?: () => void) => void;
  createReader: () => { readEntries: (ok: (entries: FsEntry[]) => void) => void };
};

export async function filesFromDataTransfer(data: DataTransfer): Promise<File[]> {
  const items = Array.from(data.items ?? []);
  const collected: File[] = [];
  const walks: Promise<void>[] = [];
  for (const item of items) {
    const entry = item.webkitGetAsEntry?.() as FsEntry | null;
    if (entry) walks.push(collectEntry(entry, collected));
  }
  if (walks.length) {
    await Promise.all(walks);
    if (collected.length) return collected;
  }
  return Array.from(data.files ?? []);
}

function collectEntry(entry: FsEntry, out: File[]): Promise<void> {
  if (entry.isFile) {
    return new Promise((resolve) => {
      entry.file(
        (file) => {
          out.push(file);
          resolve();
        },
        () => resolve()
      );
    });
  }
  if (!entry.isDirectory) return Promise.resolve();
  const reader = entry.createReader();
  return new Promise((resolve) => {
    const children: FsEntry[] = [];
    const read = () => {
      reader.readEntries((batch) => {
        if (!batch.length) {
          void Promise.all(children.map((child) => collectEntry(child, out))).then(() => resolve());
          return;
        }
        children.push(...batch);
        read();
      });
    };
    read();
  });
}

export function clipboardMediaFiles(event: ClipboardEvent): File[] {
  const fromFiles = Array.from(event.clipboardData?.files ?? []).filter((file) => mediaKind(file));
  if (fromFiles.length) return fromFiles;
  const fromItems: File[] = [];
  for (const item of Array.from(event.clipboardData?.items ?? [])) {
    if (!item.type.startsWith("image/") && !item.type.startsWith("video/")) continue;
    const file = item.getAsFile();
    if (file && mediaKind(file)) fromItems.push(file);
  }
  return fromItems;
}

export function clipboardMediaFile(event: ClipboardEvent): File | null {
  return clipboardMediaFiles(event)[0] ?? null;
}

export async function uploadRenderReference(file: File): Promise<RenderReference> {
  const out = await api.videos.upload(file);
  const kind = mediaKind(file);
  const mediaType = out.media_type === "video" || kind === "video" ? "video" : "image";
  return {
    filename: out.filename,
    mediaType,
    previewUrl: mediaApiPath(out.filename),
  };
}
