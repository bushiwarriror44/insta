import { api } from "../api/client";
import { mediaApiPath } from "../api/media";

export type RenderReference = {
  filename: string;
  mediaType: "image" | "video";
  previewUrl?: string;
};

export type RenderInputMode = "" | "image_to_video" | "video_to_video" | "image_slideshow";

export function modeForMedia(mediaType: "image" | "video"): RenderInputMode {
  return mediaType === "video" ? "video_to_video" : "image_to_video";
}

export function clipboardMediaFile(event: ClipboardEvent): File | null {
  const fromFiles = event.clipboardData?.files?.[0];
  if (fromFiles && (fromFiles.type.startsWith("image/") || fromFiles.type.startsWith("video/"))) {
    return fromFiles;
  }
  const item = Array.from(event.clipboardData?.items ?? []).find(
    (one) => one.type.startsWith("image/") || one.type.startsWith("video/")
  );
  return item?.getAsFile() ?? null;
}

export async function uploadRenderReference(file: File): Promise<RenderReference> {
  const out = await api.videos.upload(file);
  const mediaType = out.media_type === "video" ? "video" : "image";
  return {
    filename: out.filename,
    mediaType,
    previewUrl: mediaApiPath(out.filename),
  };
}
