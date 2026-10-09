import { api } from "../api/client";

const TERMINAL = new Set(["done", "failed", "dead", "cancelled"]);

export type GenerationPollRow = {
  id: number;
  status: string;
  asset_id?: number | null;
  last_error?: string | null;
  offer_local_switch?: boolean;
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
  const timeoutMs = options?.timeoutMs ?? 1_020_000;
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const row = await api.factory.getGeneration(jobId);
    if (TERMINAL.has(row.status)) {
      return row;
    }
    if (Date.now() >= deadline) {
      throw new Error(`рендер ${jobId} ещё «${row.status}» — не дождался`);
    }
    await new Promise((resolve) => window.setTimeout(resolve, intervalMs));
  }
}
