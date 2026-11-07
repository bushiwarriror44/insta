const PROMPTS = [
  { label: "Покажи аккаунты", message: "Покажи аккаунты" },
  { label: "Список видео", message: "Покажи список видео" },
  { label: "Что на панели?", message: "Что сейчас на панели?" },
  { label: "Очередь рендеров", message: "Покажи рендеры в очереди" },
] as const;

type Props = {
  onPick: (message: string) => void;
  onOpenManual?: () => void;
  allowBrowserRun?: boolean;
};

export function AssistantDockWelcome({ onPick, onOpenManual, allowBrowserRun }: Props) {
  return (
    <div
      className="rounded-xl border border-dashed border-slate-800 bg-slate-900/40 px-3 py-4"
      data-testid="assistant-dock-welcome"
    >
      <p className="text-center text-sm text-slate-400">
        Спросите агента или выберите подсказку. Списки появятся карточками под ответом; браузер VNC — с
        назначенным прокси.
        {allowBrowserRun ? " Режим с браузером включён." : ""}
      </p>
      <div className="mt-3 flex flex-wrap justify-center gap-2">
        {PROMPTS.map((item) => (
          <button
            key={item.message}
            type="button"
            className="rounded-full border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs text-slate-200 transition hover:border-sky-500/40 hover:bg-slate-800"
            onClick={() => onPick(item.message)}
          >
            {item.label}
          </button>
        ))}
      </div>
      {onOpenManual ? (
        <p className="mt-3 text-center text-[11px] text-slate-500">
          Подробнее —{" "}
          <button type="button" className="text-sky-400 hover:underline" onClick={onOpenManual}>
            мануал чата
          </button>
        </p>
      ) : null}
    </div>
  );
}
