import { apiLink, type DocSpan } from "./docText";

export type ArchitectureSection = {
  id: string;
  title: string;
  body: DocSpan[][];
};

export const ARCHITECTURE_SECTIONS: ArchitectureSection[] = [
  {
    id: "processes",
    title: "Процессы",
    body: [
      [
        "Compose по умолчанию поднимает reels-frontend (nginx и SPA), reels-api (FastAPI, Python 3.11) и reels-worker (python -m app.cli run-worker). Каталог ./data общий.",
      ],
      [
        "reels-ollama и reels-ollama-pull входят в профиль compose ollama и на админ-VPS не запускаются. Чат обращается к AGENT_BASE_URL, OpenAI-совместимому адресу, а не к localhost панели. Карточка GPU Salad вызывает ",
        apiLink("GET /api/gpu"),
        ", ",
        apiLink("POST /api/gpu/start"),
        " и ",
        apiLink("POST /api/gpu/stop"),
        ". Это не тумблер воркера и не запуск группы при старте API.",
      ],
    ],
  },
  {
    id: "ui",
    title: "UI",
    body: [
      [
        "Интерфейс собран на React 18, Vite, React Router и Tailwind. Маршруты заданы в frontend/src/App.tsx. В проде nginx отдаёт статическую сборку.",
      ],
      [
        "frontend/nginx.conf проксирует /api/ на reels-api:8000, остальные пути отдают index.html. В режиме Vite запросы /api уходят на порт 8000.",
      ],
    ],
  },
  {
    id: "api-data",
    title: "API и данные",
    body: [
      [
        "API написан на FastAPI и SQLAlchemy. SQLite, сессии аккаунтов, клипы, логи и gpu_slot.lock лежат в каталоге data/.",
      ],
      [
        "Заголовок Authorization: Bearer принимает мастер-пароль, ADMIN_TOKEN или пароль оператора. Если ни токена, ни хеша пароля нет, режим открытый и principal равен owner. Секретный путь хранится в PanelSettings.entry_path. Запрос корня без этого пути отвечает 500.",
      ],
      [
        "Схема доступна методом ",
        apiLink("GET /api/openapi.json"),
        " для открытого режима или роли owner. Маршрут /api/docs отключён.",
      ],
    ],
  },
  {
    id: "queues",
    title: "Очереди",
    body: [
      [
        "PostJob проходит uniquify через ffmpeg и затем клиент площадки. Instagram публикуется через instagrapi. YouTube Shorts и TikTok — через Playwright Studio и файл state.json.",
      ],
      [
        "GenerationJob запускает рендер по VIDEO_BACKEND и VIDEO_BACKEND_CHAIN. Composition склеивает клипы библиотеки. PlanJob ставит контент-план со страницы агента.",
      ],
      [
        "Тумблер «Агент работает» в шапке включает процесс воркера. Нижний чат и страница агента этим тумблером не управляются.",
      ],
    ],
  },
  {
    id: "generation",
    title: "Генерация",
    body: [
      [
        "Цепочка auto перебирает VIDEO_BACKEND_CHAIN до первого готового ролика. В цепочке есть Qubax, fal, Hugging Face, Pollinations и hfspace. Локальный Wan в интерфейсе отключён и в cost_usd пишет 0.",
      ],
      [
        "На видеокарте 24 ГБ чат qwen3:30b-a3b и модель экрана qwen2.5vl:7b в память одновременно не загружаются. Файл data/gpu_slot.lock удерживается на время локального рендера, если он снова включён.",
      ],
    ],
  },
  {
    id: "chat",
    title: "Чат",
    body: [
      [
        "Нижний чат ставит фоновый прогон методом ",
        apiLink("POST /api/assistant/jobs"),
        ". Состояние читается через ",
        apiLink("GET /api/assistant/jobs/active"),
        ". Модель вызывается по AGENT_BASE_URL, инструменты пишут в ту же SQLite. Справочник инструментов — docs/assistant-handbook.md.",
      ],
      [
        "Внешний клиент вызывает агента панели методом ",
        apiLink("POST /mcp"),
        ", инструмент chat. Адрес ",
        apiLink("GET /llm/v1/{path}"),
        " только пересылает запрос модели и агента не запускает. Отчёты отдаёт ",
        apiLink("GET /api/agent-reports"),
        ", журнал прогона — ",
        apiLink("GET /api/agent-reports/logs"),
        ".",
      ],
    ],
  },
  {
    id: "this-page",
    title: "Эта страница",
    body: [
      [
        "Маршрут /administration доступен владельцу. Оператору открывается редирект на /. Вкладки: обзор, блокнот и API. Блокнот хранит одну заметку в SQLite, чат её не читает и не изменяет.",
      ],
      [
        "Вкладка API показывает схему ",
        apiLink("GET /api/openapi.json"),
        ". Запросы из неё уходят с Bearer текущей сессии. Якоря Swagger отключены, чтобы они не сбрасывали выбранную вкладку.",
      ],
    ],
  },
];
