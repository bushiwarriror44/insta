import { api } from "../api/client";

const TERMINAL = new Set(["done", "failed", "dead", "cancelled"]);

export type GenerationPollRow = {
  id: number;
  status: string;
  asset_id?: number | null;
  last_error?: string | null;
  offer_local_switch?: boolean;
  poll_timeout_ms?: number;
};

export async function retryGenerationOnLocal(jobId: number): Promise<GenerationPollRow> {
  await api.factory.retryGeneration(jobId, { backend: "local" });
  return pollGenerationUntilDone(jobId);
}

export async function pollGenerationUntilDone(
  jobId: number,
  options?: { intervalMs?: number; timeoutMs?: number }
): Promise<GenerationPollRow> {
  const intervalMs = options?.intervalMs ?? 2000;
  let deadline =
    Date.now() + (options?.timeoutMs ?? 2_040_000);
  let deadlineFromApi = false;
  for (;;) {
    const row = await api.factory.getGeneration(jobId);
    if (
      !deadlineFromApi &&
      options?.timeoutMs === undefined &&
      row.poll_timeout_ms &&
      row.poll_timeout_ms > 0
    ) {
      deadline = Date.now() + row.poll_timeout_ms;
      deadlineFromApi = true;
    }
    if (TERMINAL.has(row.status)) {
      return row;
    }
    if (Date.now() >= deadline) {
      throw new Error(`рендер ${jobId} ещё «${row.status}» — не дождался`);
    }
    await new Promise((resolve) => window.setTimeout(resolve, intervalMs));
  }
}
