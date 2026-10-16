import type { GpuOut } from "../api/types";

export const START_CONFIRM =
  "После остановки образ снова качается на узел. Пока группа работает — идут GPU-часы. Запустить группу?";
export const STOP_CONFIRM =
  "Часы остановятся, чат и local-видео лягут. Остановить группу Salad?";

export function statusLabel(gpu: GpuOut): string {
  if (!gpu.configured) {
    return gpu.detail || "Salad не настроен";
  }
  switch (gpu.status) {
    case "running":
      return "Работает — идут GPU-часы";
    case "deploying":
      return "Качается образ на узел";
    case "pending":
      return "Ждёт узел";
    case "stopped":
      return "Остановлена — не тарится";
    case "failed":
      return "Сбой";
    case "succeeded":
      return "Завершена";
    default:
      return gpu.status ? gpu.status : "Статус неизвестен";
  }
}

export function canStart(gpu: GpuOut): boolean {
  if (!gpu.configured) return false;
  return gpu.status === "stopped" || gpu.status === "succeeded" || gpu.status === "failed" || gpu.status == null;
}

export function canStop(gpu: GpuOut): boolean {
  if (!gpu.configured) return false;
  return gpu.status === "running" || gpu.status === "pending" || gpu.status === "deploying";
}

export function chatLine(gpu: GpuOut): string {
  if (
    gpu.status === "deploying" ||
    gpu.status === "pending" ||
    gpu.creating_count > 0 ||
    gpu.allocating_count > 0
  ) {
    return "после запуска узла";
  }
  return gpu.chat_ok ? "отвечает" : "не отвечает";
}

export function wanLine(gpu: GpuOut): string {
  if (gpu.wan_ok == null) return "не задан";
  return gpu.wan_ok ? "отвечает" : "не отвечает";
}
