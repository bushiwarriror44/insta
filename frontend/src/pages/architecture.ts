export type ArchitectureSection = {
  id: string;
  title: string;
  body: string[];
};

export const ARCHITECTURE_SECTIONS: ArchitectureSection[] = [
  {
    id: "processes",
    title: "Процессы",
    body: [
      "Compose по умолчанию: reels-frontend (nginx, SPA), reels-api (FastAPI create_app, Python 3.11), reels-worker (python -m app.cli run-worker). Общий том ./data.",
      "reels-ollama и reels-ollama-pull в профиле compose ollama; на админ-VPS не поднимаются. Чат ходит на AGENT_BASE_URL (OpenAI-совместимый хост), не на localhost панели. Карточка GPU Salad на Администрировании запускает и останавливает группу через Salad Public API — это не тумблер воркера и не автостарт при буте API.",
    ],
  },
  {
    id: "ui",
    title: "UI",
    body: [
      "React 18, Vite, React Router, Tailwind. Маршруты: frontend/src/App.tsx. Сборка — статика за nginx.",
      "nginx (frontend/nginx.conf): /api/ проксируется на reels-api:8000; остальное — index.html. Vite dev: proxy /api → :8000.",
    ],
  },
  {
    id: "api-data",
    title: "API и данные",
    body: [
      "FastAPI + SQLAlchemy, SQLite в data/. Сессии аккаунтов, клипы, логи, gpu_slot.lock — тот же каталог.",
      "Авторизация: Authorization Bearer (мастер-пароль / ADMIN_TOKEN или пароль оператора). Если ни токена, ни хеша нет — открытый режим, principal = owner. Секретный путь панели — PanelSettings.entry_path; корень без пути отдаёт 500.",
      "Схема: GET /api/openapi.json, зависимость DocsOwnerDep (открытый режим или роль owner). /api/docs отключён (docs_url=None).",
    ],
  },
  {
    id: "queues",
    title: "Очереди",
    body: [
      "PostJob: uniquify (ffmpeg) → клиент площадки. Instagram: instagrapi. YouTube Shorts / TikTok: Playwright Studio (state.json), не Graph/Data API/OAuth.",
      "GenerationJob — рендер по VIDEO_BACKEND / VIDEO_BACKEND_CHAIN. Composition — склейка клипов библиотеки. PlanJob — контент-план со страницы /agent.",
      "Тумблер шапки «Агент работает» — процесс воркера, не нижний чат и не страница Агент.",
    ],
  },
  {
    id: "generation",
    title: "Генерация",
    body: [
      "Бэкенды: fal, huggingface, pollinations, local (WAN_BASE_URL), hfspace. auto перебирает VIDEO_BACKEND_CHAIN до первого успешного ролика.",
      "local перед POST на WAN_BASE_URL вызывает Ollama keep_alive: 0 и держит data/gpu_slot.lock. Чат в это время не грузит модель. На одной 24 GB карте чат и видео не живут в VRAM одновременно.",
    ],
  },
  {
    id: "chat",
    title: "Чат",
    body: [
      "Нижний чат: POST /api/assistant и /api/assistant/stream. Модель: AGENT_BASE_URL + /v1/chat/completions, tools пишут в ту же SQLite. Справочник: docs/assistant-handbook.md. Playwright из нижнего чата не стартует.",
      "POST /api/assistant/run и python -m app.cli ask — те же tools плюс browser-tools (start_browser). think: false в теле чата.",
    ],
  },
  {
    id: "this-page",
    title: "Эта страница",
    body: [
      "Маршрут /administration. Вкладки Обзор (GPU Salad, Оплата, Реализация), Блокнот (SQLite, чат не читает), API (swagger-ui-dist, spec /api/openapi.json только на этой вкладке). requestInterceptor добавляет Authorization Bearer из сессии, если state=authed. persistAuthorization включён. Оператору маршрут редиректит на /.",
    ],
  },
];
