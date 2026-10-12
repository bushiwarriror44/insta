import { Clapperboard } from "lucide-react";

import { Modal } from "./Modal";

export type LocalSwitchOffer = {
  job_id: number;
  message: string;
};

export function RenderLocalSwitchModal({
  offer,
  busy,
  onCancel,
  onConfirm,
}: {
  offer: LocalSwitchOffer | null;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <Modal
      open={offer !== null}
      onClose={busy ? () => undefined : onCancel}
      title="Переключить на локальный Wan?"
      footer={
        <>
          <button type="button" className="btn-ghost" disabled={busy} onClick={onCancel}>
            Отмена
          </button>
          <button type="button" className="btn-primary" disabled={busy} onClick={onConfirm}>
            Переключай
          </button>
        </>
      }
    >
      <div className="flex items-start gap-3 text-sm leading-relaxed text-slate-300">
        <Clapperboard className="mt-0.5 h-5 w-5 shrink-0 text-brand-300" />
        <p>
          {offer?.message ||
            "Сейчас сработает переключение на локальный Wan (Salad в статусе «Работает», WAN_BASE_URL). Облачные бэкенды больше не используются для этой задачи."}
        </p>
      </div>
    </Modal>
  );
}
