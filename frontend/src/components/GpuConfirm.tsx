import { Play, Square } from "lucide-react";

import { START_CONFIRM, STOP_CONFIRM } from "../lib/gpuLabels";
import { Modal } from "./Modal";

export function GpuConfirm({
  action,
  busy,
  onNo,
  onYes,
}: {
  action: "start" | "stop" | null;
  busy: boolean;
  onNo: () => void;
  onYes: () => void;
}) {
  const stopping = action === "stop";
  return (
    <Modal
      open={action !== null}
      onClose={busy ? () => undefined : onNo}
      title={stopping ? "Остановить видеокарту?" : "Запустить видеокарту?"}
      footer={
        <>
          <button type="button" className="btn-ghost" disabled={busy} onClick={onNo}>
            Нет
          </button>
          <button type="button" className="btn-primary" disabled={busy} onClick={onYes}>
            Да
          </button>
        </>
      }
    >
      <div className="flex items-start gap-3 text-sm leading-relaxed text-slate-300">
        {stopping ? (
          <Square className="mt-0.5 h-5 w-5 shrink-0 text-rose-300" />
        ) : (
          <Play className="mt-0.5 h-5 w-5 shrink-0 text-emerald-300" />
        )}
        <p>{stopping ? STOP_CONFIRM : START_CONFIRM}</p>
      </div>
    </Modal>
  );
}
